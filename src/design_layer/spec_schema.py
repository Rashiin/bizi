"""ProcessSpec: the structured, Bizagi-independent description of a process.

The design layer (LLM planner or a hardcoded sample) produces a ProcessSpec.
Everything downstream (BPMN builder, UIA builders, SQL verification) consumes it.

Conventions:
- `name` fields are ASCII identifiers (Bizagi technical names; also used as XML ids).
- `label_fa` fields are the Persian display labels.
- Every date field is Jalali (Shamsi); the schema rejects any other calendar.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

IDENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def _check_ident(value: str) -> str:
    if not IDENT_RE.match(value):
        raise ValueError(f"'{value}' is not a valid technical name (ASCII letter, then letters/digits/_)")
    return value


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Named(_Base):
    name: str

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        return _check_ident(v)


class FieldType(str, Enum):
    STRING = "string"
    TEXT = "text"  # long / multi-line text
    INTEGER = "integer"
    DECIMAL = "decimal"
    CURRENCY = "currency"
    BOOLEAN = "boolean"
    DATE = "date"
    ENTITY_REF = "entity_ref"  # many-to-one relation to another entity
    COLLECTION = "collection"  # one-to-many relation (child collection)


class EntityKind(str, Enum):
    PROCESS = "process"  # the case entity of the process
    MASTER = "master"  # regular master entity (e.g. collection items)
    PARAMETER = "parameter"  # parametric / lookup entity (e.g. Department)


class DataField(_Named):
    label_fa: str
    type: FieldType
    required: bool = False
    ref_entity: str | None = None
    calendar: Literal["jalali"] | None = None
    max_length: int | None = None

    @model_validator(mode="after")
    def _check(self) -> "DataField":
        if self.type in (FieldType.ENTITY_REF, FieldType.COLLECTION):
            if not self.ref_entity:
                raise ValueError(f"field '{self.name}': {self.type.value} requires ref_entity")
        elif self.ref_entity:
            raise ValueError(f"field '{self.name}': ref_entity only allowed for entity_ref/collection")
        if self.type == FieldType.DATE:
            # Dates are always Jalali in this project; default it rather than fail.
            if self.calendar is None:
                self.calendar = "jalali"
        elif self.calendar is not None:
            raise ValueError(f"field '{self.name}': calendar only applies to date fields")
        return self


class Entity(_Named):
    label_fa: str
    kind: EntityKind = EntityKind.MASTER
    fields: list[DataField]
    # Seed values for parameter entities (code -> Persian label).
    values: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _unique_fields(self) -> "Entity":
        names = [f.name for f in self.fields]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"entity '{self.name}': duplicate fields {sorted(dupes)}")
        return self

    def field(self, name: str) -> DataField:
        for f in self.fields:
            if f.name == name:
                return f
        raise KeyError(f"{self.name}.{name}")


class Role(_Named):
    """A Bizagi performer (role). Each role becomes a lane in BPMN."""

    label_fa: str
    description_fa: str = ""


class FormControl(_Base):
    """A control on a form, bound to an XPath relative to the process entity.

    Example xpath: "PurchaseRequest.TotalAmount" or "PurchaseRequest.Items" (grid).
    """

    xpath: str
    readonly: bool = False
    required: bool | None = None  # None = inherit from field definition


class Form(_Named):
    label_fa: str
    task: str  # the user task this form belongs to
    controls: list[FormControl]
    rtl: bool = True


class RuleKind(str, Enum):
    ON_ENTER = "on_enter"  # activity action: on enter
    ON_SAVE = "on_save"
    ON_EXIT = "on_exit"
    VALIDATION = "validation"  # on exit, throws a validation error
    CONDITION = "condition"  # gateway outgoing-flow condition


class Rule(_Named):
    """A business rule, expressed as Bizagi expression code.

    `attached_to` is a task name (for activity actions) or a flow name (for conditions).
    """

    label_fa: str
    kind: RuleKind
    attached_to: str
    code: str


class NodeType(str, Enum):
    START = "start"
    END = "end"
    USER_TASK = "user_task"
    SERVICE_TASK = "service_task"
    EXCLUSIVE_GATEWAY = "exclusive_gateway"


class FlowNode(_Named):
    label_fa: str
    type: NodeType
    role: str | None = None  # performer; required for tasks, used for lane placement


class SequenceFlow(_Named):
    source: str
    target: str
    label_fa: str = ""
    condition_rule: str | None = None  # name of a CONDITION rule
    is_default: bool = False


class ProcessSpec(_Named):
    label_fa: str
    description_fa: str = ""
    process_entity: str
    entities: list[Entity]
    roles: list[Role]
    nodes: list[FlowNode]
    flows: list[SequenceFlow]
    forms: list[Form] = Field(default_factory=list)
    rules: list[Rule] = Field(default_factory=list)

    # ---- lookups -------------------------------------------------------
    def entity(self, name: str) -> Entity:
        return _find(self.entities, name, "entity")

    def node(self, name: str) -> FlowNode:
        return _find(self.nodes, name, "node")

    def role(self, name: str) -> Role:
        return _find(self.roles, name, "role")

    def rule(self, name: str) -> Rule:
        return _find(self.rules, name, "rule")

    def resolve_xpath(self, xpath: str) -> DataField:
        """Resolve 'Entity.Field[.Field...]' to the final DataField."""
        parts = xpath.split(".")
        entity = self.entity(parts[0])
        field: DataField | None = None
        for part in parts[1:]:
            if field is not None:
                entity = self.entity(field.ref_entity)  # type: ignore[arg-type]
            field = entity.field(part)
        if field is None:
            raise KeyError(f"xpath '{xpath}' does not point to a field")
        return field

    # ---- cross-reference validation -----------------------------------
    @model_validator(mode="after")
    def _check_references(self) -> "ProcessSpec":
        errors: list[str] = []

        for kind, items in (
            ("entity", self.entities),
            ("role", self.roles),
            ("node", self.nodes),
            ("flow", self.flows),
            ("form", self.forms),
            ("rule", self.rules),
        ):
            names = [i.name for i in items]
            dupes = {n for n in names if names.count(n) > 1}
            if dupes:
                errors.append(f"duplicate {kind} names: {sorted(dupes)}")

        # Node and flow names share the BPMN id space.
        clash = {n.name for n in self.nodes} & {f.name for f in self.flows}
        if clash:
            errors.append(f"node/flow name clash: {sorted(clash)}")

        entity_names = {e.name for e in self.entities}
        if self.process_entity not in entity_names:
            errors.append(f"process_entity '{self.process_entity}' is not defined")
        elif self.entity(self.process_entity).kind != EntityKind.PROCESS:
            errors.append(f"process_entity '{self.process_entity}' must have kind=process")

        for e in self.entities:
            for f in e.fields:
                if f.ref_entity and f.ref_entity not in entity_names:
                    errors.append(f"{e.name}.{f.name}: unknown ref_entity '{f.ref_entity}'")

        role_names = {r.name for r in self.roles}
        node_names = {n.name for n in self.nodes}
        task_names = {n.name for n in self.nodes if n.type in (NodeType.USER_TASK, NodeType.SERVICE_TASK)}
        for n in self.nodes:
            if n.type == NodeType.USER_TASK and not n.role:
                errors.append(f"user task '{n.name}' has no performer role")
            if n.role and n.role not in role_names:
                errors.append(f"node '{n.name}': unknown role '{n.role}'")

        starts = [n for n in self.nodes if n.type == NodeType.START]
        ends = [n for n in self.nodes if n.type == NodeType.END]
        if len(starts) != 1:
            errors.append(f"expected exactly one start event, found {len(starts)}")
        if not ends:
            errors.append("expected at least one end event")

        rule_by_name = {r.name: r for r in self.rules}
        for fl in self.flows:
            for end in (fl.source, fl.target):
                if end not in node_names:
                    errors.append(f"flow '{fl.name}': unknown node '{end}'")
            if fl.condition_rule:
                r = rule_by_name.get(fl.condition_rule)
                if r is None:
                    errors.append(f"flow '{fl.name}': unknown rule '{fl.condition_rule}'")
                elif r.kind != RuleKind.CONDITION:
                    errors.append(f"flow '{fl.name}': rule '{r.name}' is not a condition")

        flow_names = {f.name for f in self.flows}
        for r in self.rules:
            if r.kind == RuleKind.CONDITION:
                if r.attached_to not in flow_names:
                    errors.append(f"condition rule '{r.name}': unknown flow '{r.attached_to}'")
            elif r.attached_to not in task_names:
                errors.append(f"rule '{r.name}': unknown task '{r.attached_to}'")

        # Gateways: every outgoing flow except the default needs a condition.
        for n in self.nodes:
            out = [f for f in self.flows if f.source == n.name]
            inc = [f for f in self.flows if f.target == n.name]
            if n.type == NodeType.START and inc:
                errors.append(f"start event '{n.name}' has incoming flows")
            if n.type == NodeType.END and out:
                errors.append(f"end event '{n.name}' has outgoing flows")
            if n.type != NodeType.END and not out:
                errors.append(f"node '{n.name}' has no outgoing flow")
            if n.type != NodeType.START and not inc:
                errors.append(f"node '{n.name}' is unreachable (no incoming flow)")
            if n.type == NodeType.EXCLUSIVE_GATEWAY and len(out) > 1:
                defaults = [f for f in out if f.is_default]
                if len(defaults) > 1:
                    errors.append(f"gateway '{n.name}' has more than one default flow")
                for f in out:
                    if not f.is_default and not f.condition_rule:
                        errors.append(f"gateway '{n.name}': flow '{f.name}' needs a condition or is_default")

        for form in self.forms:
            if form.task not in task_names:
                errors.append(f"form '{form.name}': unknown task '{form.task}'")
            for c in form.controls:
                try:
                    self.resolve_xpath(c.xpath)
                except KeyError as exc:
                    errors.append(f"form '{form.name}': bad xpath '{c.xpath}' ({exc})")

        if errors:
            raise ValueError("ProcessSpec is inconsistent:\n  - " + "\n  - ".join(errors))
        return self


def _find(items, name: str, kind: str):
    for i in items:
        if i.name == name:
            return i
    raise KeyError(f"unknown {kind} '{name}'")

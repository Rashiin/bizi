"""ProcessSpec -> BPMN 2.0 XML (semantic model + BPMNDI diagram).

The output is plain OMG BPMN 2.0 (no vendor extensions), validated in tests
against the official XSDs, so it can be imported into Bizagi Modeler or any
other BPMN tool. Diagram interchange (BPMNDI) is generated with a simple
automatic layout: one horizontal lane per role, one column per process step.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from src.design_layer.spec_schema import FlowNode, NodeType, ProcessSpec

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
BPMNDI_NS = "http://www.omg.org/spec/BPMN/20100524/DI"
DC_NS = "http://www.omg.org/spec/DD/20100524/DC"
DI_NS = "http://www.omg.org/spec/DD/20100524/DI"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
NSMAP = {"bpmn": BPMN_NS, "bpmndi": BPMNDI_NS, "dc": DC_NS, "di": DI_NS, "xsi": XSI_NS}

TAG = {
    NodeType.START: "startEvent",
    NodeType.END: "endEvent",
    NodeType.USER_TASK: "userTask",
    NodeType.SERVICE_TASK: "serviceTask",
    NodeType.EXCLUSIVE_GATEWAY: "exclusiveGateway",
}

# Layout constants (pixels)
SIZE = {
    NodeType.START: (36, 36),
    NodeType.END: (36, 36),
    NodeType.USER_TASK: (110, 80),
    NodeType.SERVICE_TASK: (110, 80),
    NodeType.EXCLUSIVE_GATEWAY: (50, 50),
}
POOL_X, POOL_Y = 20, 20
POOL_HEADER = 30  # vertical band holding the pool name
LANE_HEADER = 30  # vertical band holding the lane name
LANE_HEIGHT = 140
COL_WIDTH = 160
FIRST_COL_X = POOL_X + POOL_HEADER + LANE_HEADER + 30


def _b(tag: str) -> str:
    return f"{{{BPMN_NS}}}{tag}"


def _di(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


@dataclass
class _Box:
    x: float
    y: float
    w: float
    h: float

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


# ---------------------------------------------------------------- layout --
def _columns(spec: ProcessSpec) -> dict[str, int]:
    """Longest-path layering from the start event; back edges are ignored."""
    succ: dict[str, list[str]] = {n.name: [] for n in spec.nodes}
    for f in spec.flows:
        succ[f.source].append(f.target)
    start = next(n.name for n in spec.nodes if n.type == NodeType.START)

    # Find back edges with a DFS so loops (e.g. "return for revision") don't recurse forever.
    back: set[tuple[str, str]] = set()
    state: dict[str, int] = {}

    def dfs(u: str) -> None:
        state[u] = 1
        for v in succ[u]:
            if state.get(v) == 1:
                back.add((u, v))
            elif v not in state:
                dfs(v)
        state[u] = 2

    dfs(start)

    col = {n.name: 0 for n in spec.nodes}
    # Relax edges in topological order of the acyclic subgraph.
    order: list[str] = []
    seen: set[str] = set()

    def topo(u: str) -> None:
        seen.add(u)
        for v in succ[u]:
            if (u, v) not in back and v not in seen:
                topo(v)
        order.append(u)

    topo(start)
    for u in reversed(order):
        for v in succ[u]:
            if (u, v) not in back:
                col[v] = max(col[v], col[u] + 1)

    # End events sit after everything that flows into them, at the far right
    # if they are shared by several branches (e.g. a common "rejected" end).
    last = max(col.values())
    for n in spec.nodes:
        if n.type == NodeType.END and sum(1 for f in spec.flows if f.target == n.name) > 1:
            col[n.name] = last
    return col


def _lane_roles(spec: ProcessSpec) -> list[str]:
    used = {n.role for n in spec.nodes if n.role}
    return [r.name for r in spec.roles if r.name in used]


def _layout(spec: ProcessSpec) -> tuple[dict[str, _Box], dict[str, _Box], _Box]:
    cols = _columns(spec)
    lanes = _lane_roles(spec)
    n_cols = max(cols.values()) + 1
    lane_w = LANE_HEADER + 30 + n_cols * COL_WIDTH
    lane_x = POOL_X + POOL_HEADER

    lane_boxes = {
        role: _Box(lane_x, POOL_Y + i * LANE_HEIGHT, lane_w, LANE_HEIGHT) for i, role in enumerate(lanes)
    }
    pool = _Box(POOL_X, POOL_Y, POOL_HEADER + lane_w, LANE_HEIGHT * len(lanes))

    boxes: dict[str, _Box] = {}
    default_lane = lanes[0]
    for n in spec.nodes:
        w, h = SIZE[n.type]
        lane = lane_boxes[n.role or default_lane]
        cx = FIRST_COL_X + cols[n.name] * COL_WIDTH + COL_WIDTH / 2 - 30
        boxes[n.name] = _Box(cx - w / 2, lane.cy - h / 2, w, h)
    return boxes, lane_boxes, pool


def _waypoints(src: _Box, tgt: _Box, src_is_gateway: bool) -> list[tuple[float, float]]:
    if tgt.x > src.x + src.w:  # forward
        if abs(src.cy - tgt.cy) < 1:
            return [(src.x + src.w, src.cy), (tgt.x, tgt.cy)]
        if src_is_gateway:  # leave from top/bottom corner, then go right
            y0 = src.y if tgt.cy < src.cy else src.y + src.h
            return [(src.cx, y0), (src.cx, tgt.cy), (tgt.x, tgt.cy)]
        mid = (src.x + src.w + tgt.x) / 2
        return [(src.x + src.w, src.cy), (mid, src.cy), (mid, tgt.cy), (tgt.x, tgt.cy)]
    # backward / same column: route underneath both shapes
    low = max(src.y + src.h, tgt.y + tgt.h) + 25
    return [(src.cx, src.y + src.h), (src.cx, low), (tgt.cx, low), (tgt.cx, tgt.y + tgt.h)]


# --------------------------------------------------------------- builder --
def build_bpmn(spec: ProcessSpec) -> etree._ElementTree:
    pid = spec.name
    defs = etree.Element(
        _b("definitions"),
        nsmap=NSMAP,
        id=f"Definitions_{pid}",
        targetNamespace="http://bizagi-agent-poc/bpmn",
        exporter="bizagi-agent-poc",
        exporterVersion="0.1",
    )

    collab = etree.SubElement(defs, _b("collaboration"), id=f"Collaboration_{pid}")
    etree.SubElement(collab, _b("participant"), id=f"Participant_{pid}", name=spec.label_fa, processRef=pid)

    proc = etree.SubElement(defs, _b("process"), id=pid, name=spec.label_fa, isExecutable="false")
    if spec.description_fa:
        etree.SubElement(proc, _b("documentation")).text = spec.description_fa

    lane_set = etree.SubElement(proc, _b("laneSet"), id=f"LaneSet_{pid}")
    lane_roles = _lane_roles(spec)
    for role_name in lane_roles:
        role = spec.role(role_name)
        lane = etree.SubElement(lane_set, _b("lane"), id=f"Lane_{role.name}", name=role.label_fa)
        for n in spec.nodes:
            if (n.role or lane_roles[0]) == role.name:
                etree.SubElement(lane, _b("flowNodeRef")).text = n.name

    defaults = {f.source: f.name for f in spec.flows if f.is_default}
    for n in spec.nodes:
        attrs = {"id": n.name, "name": n.label_fa}
        if n.type == NodeType.EXCLUSIVE_GATEWAY and n.name in defaults:
            attrs["default"] = defaults[n.name]
        el = etree.SubElement(proc, _b(TAG[n.type]), **attrs)
        _add_task_docs(spec, n, el)
        for f in spec.flows:
            if f.target == n.name:
                etree.SubElement(el, _b("incoming")).text = f.name
        for f in spec.flows:
            if f.source == n.name:
                etree.SubElement(el, _b("outgoing")).text = f.name

    for f in spec.flows:
        attrs = {"id": f.name, "sourceRef": f.source, "targetRef": f.target}
        if f.label_fa:
            attrs["name"] = f.label_fa
        el = etree.SubElement(proc, _b("sequenceFlow"), **attrs)
        if f.condition_rule:
            cond = etree.SubElement(el, _b("conditionExpression"))
            cond.set(f"{{{XSI_NS}}}type", "bpmn:tFormalExpression")
            cond.text = spec.rule(f.condition_rule).code

    _add_diagram(defs, spec)
    return etree.ElementTree(defs)


def _add_task_docs(spec: ProcessSpec, node: FlowNode, el: etree._Element) -> None:
    """Attach form + rule summary as documentation, so it travels with the diagram."""
    if node.type not in (NodeType.USER_TASK, NodeType.SERVICE_TASK):
        return
    lines = []
    for form in spec.forms:
        if form.task == node.name:
            lines.append(f"فرم: {form.label_fa} ({form.name})")
    for rule in spec.rules:
        if rule.attached_to == node.name:
            lines.append(f"قانون [{rule.kind.value}]: {rule.label_fa} ({rule.name})")
    if node.role:
        lines.insert(0, f"نقش: {spec.role(node.role).label_fa}")
    if lines:
        etree.SubElement(el, _b("documentation")).text = "\n".join(lines)


def _bounds(parent: etree._Element, box: _Box) -> None:
    etree.SubElement(
        parent, _di(DC_NS, "Bounds"), x=_n(box.x), y=_n(box.y), width=_n(box.w), height=_n(box.h)
    )


def _label(parent: etree._Element, box: _Box) -> None:
    _bounds(etree.SubElement(parent, _di(BPMNDI_NS, "BPMNLabel")), box)


def _n(v: float) -> str:
    return str(int(round(v)))


@dataclass
class Geometry:
    """Everything needed to draw the diagram; shared by BPMNDI and the SVG preview."""

    pool: _Box
    lanes: dict[str, _Box]  # role name -> lane box
    nodes: dict[str, _Box]  # node name -> shape box
    node_labels: dict[str, _Box]  # node name -> explicit label box (gateways)
    edges: dict[str, list[tuple[float, float]]]  # flow name -> waypoints
    edge_labels: dict[str, _Box]  # flow name -> label box


def diagram_geometry(spec: ProcessSpec) -> Geometry:
    boxes, lane_boxes, pool = _layout(spec)
    node_labels = {
        # name to the upper right, clear of the top/bottom exits
        n.name: _Box(boxes[n.name].x + boxes[n.name].w + 2, boxes[n.name].y - 16, 60, 14)
        for n in spec.nodes
        if n.type == NodeType.EXCLUSIVE_GATEWAY
    }
    edges: dict[str, list[tuple[float, float]]] = {}
    edge_labels: dict[str, _Box] = {}
    for f in spec.flows:
        src_is_gw = spec.node(f.source).type == NodeType.EXCLUSIVE_GATEWAY
        points = _waypoints(boxes[f.source], boxes[f.target], src_is_gw)
        edges[f.name] = points
        if f.label_fa:  # next to the first segment
            (x0, y0), (x1, y1) = points[0], points[1]
            if x0 == x1:  # vertical exit
                edge_labels[f.name] = _Box(x0 + 4, y0 + (16 if y1 > y0 else -30), 30, 14)
            else:
                edge_labels[f.name] = _Box(x0 + 6, y0 - 18, 30, 14)
    return Geometry(pool, lane_boxes, boxes, node_labels, edges, edge_labels)


def _add_diagram(defs: etree._Element, spec: ProcessSpec) -> None:
    geo = diagram_geometry(spec)
    diagram = etree.SubElement(defs, _di(BPMNDI_NS, "BPMNDiagram"), id=f"Diagram_{spec.name}", name=spec.label_fa)
    plane = etree.SubElement(
        diagram, _di(BPMNDI_NS, "BPMNPlane"), id=f"Plane_{spec.name}", bpmnElement=f"Collaboration_{spec.name}"
    )

    shape = etree.SubElement(
        plane, _di(BPMNDI_NS, "BPMNShape"), id=f"Participant_{spec.name}_di",
        bpmnElement=f"Participant_{spec.name}", isHorizontal="true",
    )
    _bounds(shape, geo.pool)
    for role, box in geo.lanes.items():
        shape = etree.SubElement(
            plane, _di(BPMNDI_NS, "BPMNShape"), id=f"Lane_{role}_di", bpmnElement=f"Lane_{role}", isHorizontal="true"
        )
        _bounds(shape, box)

    for n in spec.nodes:
        attrs = {"id": f"{n.name}_di", "bpmnElement": n.name}
        if n.type == NodeType.EXCLUSIVE_GATEWAY:
            attrs["isMarkerVisible"] = "true"
        shape = etree.SubElement(plane, _di(BPMNDI_NS, "BPMNShape"), **attrs)
        _bounds(shape, geo.nodes[n.name])
        if n.name in geo.node_labels:
            _label(shape, geo.node_labels[n.name])

    for f in spec.flows:
        edge = etree.SubElement(plane, _di(BPMNDI_NS, "BPMNEdge"), id=f"{f.name}_di", bpmnElement=f.name)
        for x, y in geo.edges[f.name]:
            etree.SubElement(edge, _di(DI_NS, "waypoint"), x=_n(x), y=_n(y))
        if f.name in geo.edge_labels:
            _label(edge, geo.edge_labels[f.name])


def to_xml_bytes(spec: ProcessSpec) -> bytes:
    return etree.tostring(build_bpmn(spec), xml_declaration=True, encoding="UTF-8", pretty_print=True)


def write_bpmn(spec: ProcessSpec, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(to_xml_bytes(spec))
    return path

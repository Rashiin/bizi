"""Hardcoded sample: purchase request with three approval levels.

Works without an LLM; it is the baseline for tests and for the demo.

Flow:
  start -> RegisterRequest (requester)
        -> ManagerApproval  -> [approved?] --no--> RequestRejected
        -> FinanceApproval  -> [approved?] --no--> RequestRejected
        -> CeoApproval      -> [approved?] --no--> RequestRejected
        -> PerformPurchase (procurement) -> PurchaseCompleted

Rule code is Bizagi expression syntax. It still has to be checked against the
live Studio expression editor (Studio 11.2.5) before it is relied on.
"""

from __future__ import annotations

from .spec_schema import (
    DataField,
    Entity,
    EntityKind,
    FieldType,
    FlowNode,
    Form,
    FormControl,
    NodeType,
    ProcessSpec,
    Role,
    Rule,
    RuleKind,
    SequenceFlow,
)

F = FieldType
P = "PurchaseRequest"


def _approval_level(level: str, label_fa: str, role: str, next_node: str) -> tuple[list, list, list, list]:
    """Task + gateway + flows + condition rule for one approval level."""
    task, gw = f"{level}Approval", f"{level}Decision"
    nodes = [
        FlowNode(name=task, label_fa=f"تأیید {label_fa}", type=NodeType.USER_TASK, role=role),
        FlowNode(name=gw, label_fa="تأیید شد؟", type=NodeType.EXCLUSIVE_GATEWAY, role=role),
    ]
    flows = [
        SequenceFlow(name=f"Flow_{task}_to_{gw}", source=task, target=gw),
        SequenceFlow(
            name=f"Flow_{gw}_Yes",
            source=gw,
            target=next_node,
            label_fa="بله",
            condition_rule=f"{level}Approved",
        ),
        SequenceFlow(
            name=f"Flow_{gw}_No", source=gw, target="RequestRejected", label_fa="خیر", is_default=True
        ),
    ]
    rules = [
        Rule(
            name=f"{level}Approved",
            label_fa=f"تأیید {label_fa}",
            kind=RuleKind.CONDITION,
            attached_to=f"Flow_{gw}_Yes",
            code=f"<{P}.{level}Approved> == true",
        ),
        Rule(
            name=f"Validate{level}Comment",
            label_fa=f"توضیح الزامی در صورت رد توسط {label_fa}",
            kind=RuleKind.VALIDATION,
            attached_to=task,
            code=(
                f"if (<{P}.{level}Approved> != true && BAUtil.isNull(<{P}.{level}Comment>))\n"
                "{\n"
                f'    CHelper.ThrowValidationError("در صورت رد درخواست، ثبت توضیحات {label_fa} الزامی است.");\n'
                "}"
            ),
        ),
        Rule(
            name=f"Stamp{level}Date",
            label_fa=f"ثبت تاریخ تصمیم {label_fa}",
            kind=RuleKind.ON_EXIT,
            attached_to=task,
            code=f"<{P}.{level}DecisionDate> = DateTime.Now;",
        ),
    ]
    approval_controls = [
        FormControl(xpath=f"{P}.RequestNumber", readonly=True),
        FormControl(xpath=f"{P}.RequestDate", readonly=True),
        FormControl(xpath=f"{P}.Department", readonly=True),
        FormControl(xpath=f"{P}.Description", readonly=True),
        FormControl(xpath=f"{P}.Items", readonly=True),
        FormControl(xpath=f"{P}.TotalAmount", readonly=True),
    ]
    # Later levels see earlier decisions read-only.
    for prev in ("Manager", "Finance", "Ceo"):
        if prev == level:
            break
        approval_controls += [
            FormControl(xpath=f"{P}.{prev}Approved", readonly=True),
            FormControl(xpath=f"{P}.{prev}Comment", readonly=True),
        ]
    approval_controls += [
        FormControl(xpath=f"{P}.{level}Approved", required=True),
        FormControl(xpath=f"{P}.{level}Comment"),
    ]
    forms = [Form(name=f"Form{task}", label_fa=f"فرم تأیید {label_fa}", task=task, controls=approval_controls)]
    return nodes, flows, rules, forms


def build_sample_purchase() -> ProcessSpec:
    entities = [
        Entity(
            name="Department",
            label_fa="واحد سازمانی",
            kind=EntityKind.PARAMETER,
            fields=[
                DataField(name="Code", label_fa="کد", type=F.STRING, required=True, max_length=20),
                DataField(name="Name", label_fa="نام", type=F.STRING, required=True, max_length=100),
            ],
            values={"FIN": "مالی", "IT": "فناوری اطلاعات", "OPS": "عملیات", "HR": "منابع انسانی"},
        ),
        Entity(
            name="UnitOfMeasure",
            label_fa="واحد سنجش",
            kind=EntityKind.PARAMETER,
            fields=[
                DataField(name="Code", label_fa="کد", type=F.STRING, required=True, max_length=20),
                DataField(name="Name", label_fa="نام", type=F.STRING, required=True, max_length=50),
            ],
            values={"PCS": "عدد", "BOX": "جعبه", "KG": "کیلوگرم", "M": "متر"},
        ),
        Entity(
            name="PurchaseItem",
            label_fa="قلم خرید",
            kind=EntityKind.MASTER,
            fields=[
                DataField(name="ItemName", label_fa="شرح کالا", type=F.STRING, required=True, max_length=200),
                DataField(name="Quantity", label_fa="تعداد", type=F.DECIMAL, required=True),
                DataField(name="Unit", label_fa="واحد", type=F.ENTITY_REF, ref_entity="UnitOfMeasure", required=True),
                DataField(name="UnitPrice", label_fa="قیمت واحد (ریال)", type=F.CURRENCY, required=True),
                DataField(name="LineTotal", label_fa="مبلغ کل ردیف (ریال)", type=F.CURRENCY),
            ],
        ),
        Entity(
            name=P,
            label_fa="درخواست خرید",
            kind=EntityKind.PROCESS,
            fields=[
                DataField(name="RequestNumber", label_fa="شماره درخواست", type=F.STRING, max_length=30),
                DataField(name="RequestDate", label_fa="تاریخ درخواست", type=F.DATE),
                DataField(name="RequesterName", label_fa="نام درخواست‌کننده", type=F.STRING, max_length=100),
                DataField(name="Department", label_fa="واحد درخواست‌کننده", type=F.ENTITY_REF,
                          ref_entity="Department", required=True),
                DataField(name="NeededByDate", label_fa="تاریخ نیاز", type=F.DATE, required=True),
                DataField(name="Description", label_fa="شرح درخواست", type=F.TEXT, required=True),
                DataField(name="Items", label_fa="اقلام درخواستی", type=F.COLLECTION, ref_entity="PurchaseItem"),
                DataField(name="TotalAmount", label_fa="مبلغ کل (ریال)", type=F.CURRENCY),
                DataField(name="ManagerApproved", label_fa="تأیید مدیر واحد", type=F.BOOLEAN),
                DataField(name="ManagerComment", label_fa="توضیحات مدیر واحد", type=F.TEXT),
                DataField(name="ManagerDecisionDate", label_fa="تاریخ تصمیم مدیر واحد", type=F.DATE),
                DataField(name="FinanceApproved", label_fa="تأیید مدیر مالی", type=F.BOOLEAN),
                DataField(name="FinanceComment", label_fa="توضیحات مدیر مالی", type=F.TEXT),
                DataField(name="FinanceDecisionDate", label_fa="تاریخ تصمیم مدیر مالی", type=F.DATE),
                DataField(name="CeoApproved", label_fa="تأیید مدیرعامل", type=F.BOOLEAN),
                DataField(name="CeoComment", label_fa="توضیحات مدیرعامل", type=F.TEXT),
                DataField(name="CeoDecisionDate", label_fa="تاریخ تصمیم مدیرعامل", type=F.DATE),
                DataField(name="PurchaseOrderNumber", label_fa="شماره سفارش خرید", type=F.STRING, max_length=30),
                DataField(name="PurchaseDate", label_fa="تاریخ خرید", type=F.DATE),
            ],
        ),
    ]

    roles = [
        Role(name="Requester", label_fa="درخواست‌کننده", description_fa="کارمند ثبت‌کنندهٔ درخواست خرید"),
        Role(name="DepartmentManager", label_fa="مدیر واحد"),
        Role(name="FinanceManager", label_fa="مدیر مالی"),
        Role(name="CEO", label_fa="مدیرعامل"),
        Role(name="ProcurementOfficer", label_fa="کارشناس تدارکات"),
    ]

    nodes = [
        FlowNode(name="StartPurchase", label_fa="شروع", type=NodeType.START, role="Requester"),
        FlowNode(name="RegisterRequest", label_fa="ثبت درخواست خرید", type=NodeType.USER_TASK, role="Requester"),
    ]
    flows = [SequenceFlow(name="Flow_Start_to_Register", source="StartPurchase", target="RegisterRequest"),
             SequenceFlow(name="Flow_Register_to_Manager", source="RegisterRequest", target="ManagerApproval")]
    rules = [
        Rule(
            name="InitRequest",
            label_fa="مقداردهی اولیهٔ درخواست",
            kind=RuleKind.ON_ENTER,
            attached_to="RegisterRequest",
            code=(
                f"<{P}.RequestDate> = DateTime.Today;\n"
                f"<{P}.RequestNumber> = \"PR-\" + Me.Case.CaseNumber;\n"
                f"<{P}.RequesterName> = Me.Case.WorkingCredential.FullName;"
            ),
        ),
        Rule(
            name="CalculateTotal",
            label_fa="محاسبهٔ مبلغ کل",
            kind=RuleKind.ON_SAVE,
            attached_to="RegisterRequest",
            code=(
                "var total = 0;\n"
                f"var items = Me.getXPath(\"{P}.Items\");\n"
                "for (var i = 0; i < items.size(); i++)\n"
                "{\n"
                "    var item = items.get(i);\n"
                "    var line = CHelper.ToDecimal(item.getXPath(\"Quantity\")) * CHelper.ToDecimal(item.getXPath(\"UnitPrice\"));\n"
                "    item.setXPath(\"LineTotal\", line);\n"
                "    total = total + line;\n"
                "}\n"
                f"<{P}.TotalAmount> = total;"
            ),
        ),
        Rule(
            name="ValidateRequest",
            label_fa="اعتبارسنجی درخواست",
            kind=RuleKind.VALIDATION,
            attached_to="RegisterRequest",
            code=(
                f"if (Me.getXPath(\"count({P}.Items)\") == 0)\n"
                "{\n"
                "    CHelper.ThrowValidationError(\"حداقل یک قلم کالا باید ثبت شود.\");\n"
                "}\n"
                f"if (<{P}.NeededByDate> < DateTime.Today)\n"
                "{\n"
                "    CHelper.ThrowValidationError(\"تاریخ نیاز نمی‌تواند قبل از امروز باشد.\");\n"
                "}"
            ),
        ),
    ]
    forms = [
        Form(
            name="FormRegisterRequest",
            label_fa="فرم ثبت درخواست خرید",
            task="RegisterRequest",
            controls=[
                FormControl(xpath=f"{P}.RequestNumber", readonly=True),
                FormControl(xpath=f"{P}.RequestDate", readonly=True),
                FormControl(xpath=f"{P}.RequesterName", readonly=True),
                FormControl(xpath=f"{P}.Department"),
                FormControl(xpath=f"{P}.NeededByDate"),
                FormControl(xpath=f"{P}.Description"),
                FormControl(xpath=f"{P}.Items"),
                FormControl(xpath=f"{P}.TotalAmount", readonly=True),
            ],
        )
    ]

    for level, label, role, nxt in (
        ("Manager", "مدیر واحد", "DepartmentManager", "FinanceApproval"),
        ("Finance", "مدیر مالی", "FinanceManager", "CeoApproval"),
        ("Ceo", "مدیرعامل", "CEO", "PerformPurchase"),
    ):
        n, f, r, fm = _approval_level(level, label, role, nxt)
        nodes += n
        flows += f
        rules += r
        forms += fm

    nodes += [
        FlowNode(name="PerformPurchase", label_fa="انجام خرید و ثبت سفارش", type=NodeType.USER_TASK,
                 role="ProcurementOfficer"),
        FlowNode(name="PurchaseCompleted", label_fa="خرید انجام شد", type=NodeType.END, role="ProcurementOfficer"),
        FlowNode(name="RequestRejected", label_fa="درخواست رد شد", type=NodeType.END, role="Requester"),
    ]
    flows.append(SequenceFlow(name="Flow_Purchase_to_End", source="PerformPurchase", target="PurchaseCompleted"))
    rules.append(
        Rule(
            name="StampPurchaseDate",
            label_fa="ثبت تاریخ خرید",
            kind=RuleKind.ON_EXIT,
            attached_to="PerformPurchase",
            code=f"<{P}.PurchaseDate> = DateTime.Today;",
        )
    )
    forms.append(
        Form(
            name="FormPerformPurchase",
            label_fa="فرم انجام خرید",
            task="PerformPurchase",
            controls=[
                FormControl(xpath=f"{P}.RequestNumber", readonly=True),
                FormControl(xpath=f"{P}.Department", readonly=True),
                FormControl(xpath=f"{P}.Items", readonly=True),
                FormControl(xpath=f"{P}.TotalAmount", readonly=True),
                FormControl(xpath=f"{P}.CeoComment", readonly=True),
                FormControl(xpath=f"{P}.PurchaseOrderNumber", required=True),
            ],
        )
    )

    return ProcessSpec(
        name="PurchaseRequestProcess",
        label_fa="فرآیند درخواست خرید",
        description_fa="درخواست خرید کالا با سه سطح تأیید: مدیر واحد، مدیر مالی و مدیرعامل.",
        process_entity=P,
        entities=entities,
        roles=roles,
        nodes=nodes,
        flows=flows,
        forms=forms,
        rules=rules,
    )



if __name__ == "__main__":
    print(build_sample_purchase().model_dump_json(indent=2))

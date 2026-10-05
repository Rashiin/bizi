from pathlib import Path

import pytest
from lxml import etree

from src.bpmn.bpmn_builder import BPMN_NS, BPMNDI_NS, to_xml_bytes
from src.bpmn.preview import build_preview_html
from src.bpmn.svg_render import render_svg
from src.design_layer.sample_purchase import build_sample_purchase
from src.design_layer.spec_schema import FieldType, NodeType, ProcessSpec

XSD = Path(__file__).parent / "schemas" / "bpmn20" / "BPMN20.xsd"
NS = {"bpmn": BPMN_NS, "bpmndi": BPMNDI_NS}


@pytest.fixture(scope="module")
def spec() -> ProcessSpec:
    return build_sample_purchase()


@pytest.fixture(scope="module")
def doc(spec):
    return etree.fromstring(to_xml_bytes(spec))


def test_xml_is_schema_valid(doc):
    schema = etree.XMLSchema(etree.parse(str(XSD)))
    assert schema.validate(doc), schema.error_log


def test_persian_names_survive_utf8(spec, doc):
    proc = doc.find("bpmn:process", NS)
    assert proc.get("name") == "فرآیند درخواست خرید"
    assert doc.find(".//bpmn:userTask[@id='RegisterRequest']", NS).get("name") == "ثبت درخواست خرید"


def test_every_node_and_flow_is_emitted(spec, doc):
    ids = {el.get("id") for el in doc.iter()}
    for n in spec.nodes:
        assert n.name in ids
    for f in spec.flows:
        assert f.name in ids
    assert len(doc.findall(".//bpmn:userTask", NS)) == 5
    assert len(doc.findall(".//bpmn:exclusiveGateway", NS)) == 3


def test_every_element_has_diagram_info(spec, doc):
    drawn = {el.get("bpmnElement") for el in doc.findall(".//bpmndi:BPMNShape", NS)}
    drawn |= {el.get("bpmnElement") for el in doc.findall(".//bpmndi:BPMNEdge", NS)}
    expected = {n.name for n in spec.nodes} | {f.name for f in spec.flows}
    expected |= {f"Lane_{r.name}" for r in spec.roles}
    assert expected <= drawn


def test_one_lane_per_role_and_each_node_in_exactly_one_lane(spec, doc):
    lanes = doc.findall(".//bpmn:lane", NS)
    assert {lane.get("id") for lane in lanes} == {f"Lane_{r.name}" for r in spec.roles}
    refs = [ref.text for lane in lanes for ref in lane.findall("bpmn:flowNodeRef", NS)]
    assert sorted(refs) == sorted(n.name for n in spec.nodes)


def test_gateways_have_default_and_conditions(doc):
    for gw in doc.findall(".//bpmn:exclusiveGateway", NS):
        default = gw.get("default")
        assert default, gw.get("id")
        outgoing = [o.text for o in gw.findall("bpmn:outgoing", NS)]
        for flow_id in outgoing:
            flow = doc.find(f".//bpmn:sequenceFlow[@id='{flow_id}']", NS)
            has_cond = flow.find("bpmn:conditionExpression", NS) is not None
            assert has_cond != (flow_id == default)


def test_three_approval_levels(spec):
    approvals = [n for n in spec.nodes if n.type == NodeType.USER_TASK and n.name.endswith("Approval")]
    assert [n.role for n in approvals] == ["DepartmentManager", "FinanceManager", "CEO"]


def test_all_dates_are_jalali(spec):
    dates = [f for e in spec.entities for f in e.fields if f.type == FieldType.DATE]
    assert dates and all(f.calendar == "jalali" for f in dates)


def test_every_user_task_has_a_form(spec):
    tasks = {n.name for n in spec.nodes if n.type == NodeType.USER_TASK}
    assert tasks == {f.task for f in spec.forms}
    assert all(f.rtl for f in spec.forms)


def test_spec_rejects_broken_references(spec):
    data = spec.model_dump()
    data["flows"][0]["target"] = "NoSuchNode"
    with pytest.raises(ValueError, match="unknown node 'NoSuchNode'"):
        ProcessSpec.model_validate(data)


def test_spec_rejects_bad_form_xpath(spec):
    data = spec.model_dump()
    data["forms"][0]["controls"][0]["xpath"] = "PurchaseRequest.Nope"
    with pytest.raises(ValueError, match="bad xpath"):
        ProcessSpec.model_validate(data)


def test_spec_rejects_non_ascii_technical_name(spec):
    data = spec.model_dump()
    data["roles"][0]["name"] = "درخواست"
    with pytest.raises(ValueError, match="not a valid technical name"):
        ProcessSpec.model_validate(data)


def test_spec_json_roundtrip(spec):
    again = ProcessSpec.model_validate_json(spec.model_dump_json())
    assert again == spec


def test_preview_is_static_and_draws_every_node(spec):
    html = build_preview_html(spec)
    assert "<script" not in html  # must render in print/PDF/screenshot tools without JS
    assert "فرم ثبت درخواست خرید" in html
    svg = etree.fromstring(render_svg(spec).encode("utf-8"))  # well-formed XML
    texts = " ".join(t.text or "" for t in svg.iter("{http://www.w3.org/2000/svg}text"))
    for n in spec.nodes:
        for word in n.label_fa.split():
            assert word in texts, n.name

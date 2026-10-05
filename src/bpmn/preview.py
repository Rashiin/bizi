"""Self-contained HTML preview of a ProcessSpec: BPMN diagram + data model + forms + rules.

Runs on any OS (no Bizagi needed) and works offline: bpmn-js is inlined from
src/bpmn/vendor. Useful for reviewing the design layer before it is built in Studio.
"""

from __future__ import annotations

import json
import re
from html import escape
from pathlib import Path

from src.bpmn.bpmn_builder import to_xml_bytes
from src.design_layer.spec_schema import DataField, EntityKind, FieldType, ProcessSpec, RuleKind

VENDOR = Path(__file__).parent / "vendor"

TYPE_FA = {
    FieldType.STRING: "متن کوتاه",
    FieldType.TEXT: "متن بلند",
    FieldType.INTEGER: "عدد صحیح",
    FieldType.DECIMAL: "عدد اعشاری",
    FieldType.CURRENCY: "مبلغ",
    FieldType.BOOLEAN: "بله/خیر",
    FieldType.DATE: "تاریخ",
    FieldType.ENTITY_REF: "ارجاع",
    FieldType.COLLECTION: "مجموعه",
}
KIND_FA = {EntityKind.PROCESS: "موجودیت فرآیند", EntityKind.MASTER: "موجودیت اصلی", EntityKind.PARAMETER: "موجودیت پارامتری"}
RULE_FA = {
    RuleKind.ON_ENTER: "هنگام ورود",
    RuleKind.ON_SAVE: "هنگام ذخیره",
    RuleKind.ON_EXIT: "هنگام خروج",
    RuleKind.VALIDATION: "اعتبارسنجی",
    RuleKind.CONDITION: "شرط مسیر",
}

CSS = """
:root{--bg:#f7f7f8;--card:#fff;--ink:#1d1d1f;--muted:#6b6b75;--line:#e3e3e8;--accent:#2f6fde;--ro:#f1f1f4}
@media (prefers-color-scheme:dark){:root{--bg:#141416;--card:#1e1e22;--ink:#ececf1;--muted:#a0a0ab;--line:#33333a;--accent:#7aa5ff;--ro:#26262b}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.7 Vazirmatn,Tahoma,"Segoe UI",sans-serif}
main{max-width:1200px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:19px;margin:36px 0 12px}h3{font-size:16px;margin:0 0 10px}
.muted{color:var(--muted)}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:14px}
#canvas{height:min(620px,70vh);background:#fff;border:1px solid var(--line);border-radius:10px;direction:ltr}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:right;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600}
code,pre{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px}
pre{direction:ltr;text-align:left;background:var(--ro);padding:10px;border-radius:8px;overflow:auto;margin:6px 0 0}
.tag{display:inline-block;font-size:12px;padding:0 8px;border-radius:99px;background:var(--ro);color:var(--muted);margin-inline-start:6px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:14px}
.form .row{display:grid;grid-template-columns:160px 1fr;gap:8px;align-items:start;margin-bottom:8px}
.form label{color:var(--muted);font-size:14px;padding-top:6px}
.form input:not([type=radio]),.form select,.form textarea{width:100%;font:inherit;padding:5px 8px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--ink)}
.form [disabled]{background:var(--ro)}
.radios{display:flex;gap:18px;padding-top:6px}.radios label{color:var(--ink);padding:0}
.req::after{content:" *";color:#d33}
.mini th,.mini td{font-size:12px;padding:4px}
.form .row.wide{grid-template-columns:1fr}
@media (max-width:600px){.form .row{grid-template-columns:1fr}.grid{grid-template-columns:1fr}}
"""


def _control_html(spec: ProcessSpec, field: DataField, readonly: bool) -> str:
    dis = " disabled" if readonly else ""
    if field.type == FieldType.DATE:
        return f'<input placeholder="۱۴۰۵/۰۷/۱۳" title="تاریخ شمسی"{dis}>'
    if field.type == FieldType.TEXT:
        return f"<textarea rows=2{dis}></textarea>"
    if field.type == FieldType.BOOLEAN:
        return (
            f'<span class="radios"><label><input type=radio name="{field.name}"{dis}> بله</label>'
            f'<label><input type=radio name="{field.name}"{dis}> خیر</label></span>'
        )
    if field.type == FieldType.ENTITY_REF:
        ref = spec.entity(field.ref_entity)  # type: ignore[arg-type]
        opts = "".join(f"<option>{escape(v)}</option>" for v in ref.values.values())
        return f"<select{dis}><option>— انتخاب {escape(ref.label_fa)} —</option>{opts}</select>"
    if field.type == FieldType.COLLECTION:
        child = spec.entity(field.ref_entity)  # type: ignore[arg-type]
        head = "".join(f"<th>{escape(f.label_fa)}</th>" for f in child.fields)
        return f'<table class="mini"><tr>{head}</tr><tr>{"<td>…</td>" * len(child.fields)}</tr></table>'
    return f"<input{dis}>"


def _section_data_model(spec: ProcessSpec) -> str:
    out = ['<h2>مدل داده</h2><div class="grid">']
    for e in spec.entities:
        rows = []
        for f in e.fields:
            t = TYPE_FA[f.type]
            if f.ref_entity:
                t += f" → {escape(spec.entity(f.ref_entity).label_fa)}"
            if f.calendar == "jalali":
                t += ' <span class="tag">شمسی</span>'
            rows.append(
                f"<tr><td>{escape(f.label_fa)}</td><td><code>{f.name}</code></td><td>{t}</td>"
                f"<td>{'✓' if f.required else ''}</td></tr>"
            )
        values = ""
        if e.values:
            values = '<p class="muted">مقادیر: ' + "، ".join(escape(v) for v in e.values.values()) + "</p>"
        out.append(
            f'<div class="card"><h3>{escape(e.label_fa)} <code>{e.name}</code>'
            f'<span class="tag">{KIND_FA[e.kind]}</span></h3>'
            f"<table><tr><th>برچسب</th><th>نام فنی</th><th>نوع</th><th>الزامی</th></tr>{''.join(rows)}</table>"
            f"{values}</div>"
        )
    out.append("</div>")
    return "".join(out)


def _section_forms(spec: ProcessSpec) -> str:
    out = ['<h2>فرم‌ها <span class="tag">راست‌چین</span></h2><div class="grid">']
    for form in spec.forms:
        task = spec.node(form.task)
        rows = []
        for c in form.controls:
            field = spec.resolve_xpath(c.xpath)
            required = field.required if c.required is None else c.required
            cls = ' class="req"' if required and not c.readonly else ""
            wide = " wide" if field.type == FieldType.COLLECTION else ""
            rows.append(
                f'<div class="row{wide}"><label{cls}>{escape(field.label_fa)}</label>'
                f"{_control_html(spec, field, c.readonly)}</div>"
            )
        role = spec.role(task.role).label_fa if task.role else ""
        out.append(
            f'<div class="card form" dir="rtl"><h3>{escape(form.label_fa)}</h3>'
            f'<p class="muted">فعالیت: {escape(task.label_fa)} — نقش: {escape(role)}</p>{"".join(rows)}</div>'
        )
    out.append("</div>")
    return "".join(out)


PERSIAN_LITERAL = re.compile(r'"([^"\n]*[\u0600-\u06FF][^"\n]*)"')


def _code_html(code: str) -> str:
    """Escape code; wrap Persian string literals in <bdi> so punctuation stays inside the quotes."""
    return PERSIAN_LITERAL.sub(r'"<bdi>\1</bdi>"', escape(code, quote=False))


def _section_rules(spec: ProcessSpec) -> str:
    out = ["<h2>قوانین کسب‌وکار</h2>"]
    for r in spec.rules:
        target = r.attached_to
        if r.kind != RuleKind.CONDITION:
            target = spec.node(r.attached_to).label_fa
        out.append(
            f'<div class="card"><h3>{escape(r.label_fa)} <code>{r.name}</code>'
            f'<span class="tag">{RULE_FA[r.kind]}</span></h3>'
            f'<div class="muted">روی: {escape(target)}</div><pre>{_code_html(r.code)}</pre></div>'
        )
    return "".join(out)


def _section_roles(spec: ProcessSpec) -> str:
    rows = "".join(
        f"<tr><td>{escape(r.label_fa)}</td><td><code>{r.name}</code></td><td>"
        + "، ".join(escape(n.label_fa) for n in spec.nodes if n.role == r.name and n.type.value.endswith("task"))
        + "</td></tr>"
        for r in spec.roles
    )
    return (
        '<h2>نقش‌ها (Performer)</h2><div class="card"><table>'
        f"<tr><th>نقش</th><th>نام فنی</th><th>فعالیت‌ها</th></tr>{rows}</table></div>"
    )


def build_preview_html(spec: ProcessSpec) -> str:
    xml = to_xml_bytes(spec).decode("utf-8")
    viewer_js = (VENDOR / "bpmn-navigated-viewer.production.min.js").read_text(encoding="utf-8")
    viewer_css = (VENDOR / "diagram-js.css").read_text(encoding="utf-8") + (VENDOR / "bpmn-js.css").read_text(
        encoding="utf-8"
    )
    xml_js = json.dumps(xml).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="fa">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(spec.label_fa)}</title>
<style>{viewer_css}</style>
<style>{CSS}</style>
</head>
<body>
<!-- body stays LTR: bpmn-js measures label text in document.body -->
<main dir="rtl">
<h1>{escape(spec.label_fa)}</h1>
<p class="muted">{escape(spec.description_fa)}</p>
<p class="muted">{len(spec.entities)} موجودیت · {len(spec.forms)} فرم · {len(spec.rules)} قانون · {len(spec.roles)} نقش</p>
<h2>نمودار فرآیند (BPMN 2.0)</h2>
<div id="canvas"></div>
{_section_roles(spec)}
{_section_data_model(spec)}
{_section_forms(spec)}
{_section_rules(spec)}
</main>
<script>{viewer_js}</script>
<script>
const xml = {xml_js};
const viewer = new BpmnJS({{ container: '#canvas' }});
const fit = () => viewer.get('canvas').zoom('fit-viewport', 'auto');
viewer.importXML(xml).then(() => {{ fit(); new ResizeObserver(fit).observe(document.getElementById('canvas')); }})
  .catch(err => {{ document.getElementById('canvas').textContent = 'خطا در نمایش BPMN: ' + err.message; }});
</script>
</body>
</html>
"""


def write_preview(spec: ProcessSpec, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_preview_html(spec), encoding="utf-8")
    return path

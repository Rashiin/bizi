"""Static SVG rendering of the process diagram, from the same geometry as the BPMNDI.

No JavaScript: the diagram shows up in any browser, print, PDF export or
full-page screenshot tool. Colors come from CSS variables of the host page
(--ink, --card, --muted, --lane) so it follows light/dark mode.
"""

from __future__ import annotations

from html import escape

from src.bpmn.bpmn_builder import POOL_HEADER, LANE_HEADER, _Box, diagram_geometry
from src.design_layer.spec_schema import NodeType, ProcessSpec

FONT = "Vazirmatn,Tahoma,'Segoe UI',sans-serif"
MARGIN = 10


def _wrap(text: str, max_chars: int) -> list[str]:
    lines: list[str] = []
    for word in text.split():
        if lines and len(lines[-1]) + 1 + len(word) <= max_chars:
            lines[-1] += " " + word
        else:
            lines.append(word)
    return lines or [""]


def _text(
    x: float, y: float, text: str, size: int = 12, anchor: str = "middle", cls: str = "", extra: str = "",
    direction: str = "rtl",
) -> str:
    c = f' class="{cls}"' if cls else ""
    return (
        f'<text x="{x:.0f}" y="{y:.0f}" font-size="{size}" text-anchor="{anchor}" direction="{direction}"'
        f' dominant-baseline="middle"{c}{extra}>{escape(text)}</text>'
    )


def _multiline(cx: float, cy: float, text: str, max_chars: int, size: int = 12) -> str:
    lines = _wrap(text, max_chars)
    lh = size + 3
    top = cy - (len(lines) - 1) * lh / 2
    return "".join(_text(cx, top + i * lh, line, size) for i, line in enumerate(lines))


def _label_at(box: _Box, text: str, size: int = 11) -> str:
    # Label boxes come from BPMNDI and are anchored on their left edge.
    return _text(box.x, box.cy, text, size, anchor="start", cls="lbl", direction="ltr")


def render_svg(spec: ProcessSpec) -> str:
    geo = diagram_geometry(spec)
    p = geo.pool
    max_y = max([p.y + p.h] + [y for pts in geo.edges.values() for _, y in pts]) + 30
    x0, y0, w, h = p.x - MARGIN, p.y - MARGIN, p.w + 2 * MARGIN, max_y - p.y + MARGIN
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0:.0f} {y0:.0f} {w:.0f} {h:.0f}" role="img"'
        f' aria-label="{escape(spec.label_fa)}" font-family="{FONT}" class="bpmn">',
        "<defs>"
        '<marker id="arrow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="8" markerHeight="8" orient="auto">'
        '<path d="M0,0 L10,5 L0,10 z" class="arrowhead"/></marker>'
        "</defs>",
    ]

    # Pool and lanes; names are written vertically in the header bands.
    out.append(f'<rect x="{p.x}" y="{p.y}" width="{p.w}" height="{p.h}" class="pool"/>')
    out.append(
        f'<line x1="{p.x + POOL_HEADER}" y1="{p.y}" x2="{p.x + POOL_HEADER}" y2="{p.y + p.h}" class="pool"/>'
    )
    cx, cy = p.x + POOL_HEADER / 2, p.cy
    out.append(_text(cx, cy, spec.label_fa, 13, extra=f' transform="rotate(-90 {cx:.0f} {cy:.0f})" font-weight="600"'))
    for i, (role, lane) in enumerate(geo.lanes.items()):
        if i % 2:
            out.append(f'<rect x="{lane.x}" y="{lane.y}" width="{lane.w}" height="{lane.h}" class="lane-alt"/>')
        out.append(f'<rect x="{lane.x}" y="{lane.y}" width="{lane.w}" height="{lane.h}" class="lane"/>')
        out.append(
            f'<line x1="{lane.x + LANE_HEADER}" y1="{lane.y}" x2="{lane.x + LANE_HEADER}" y2="{lane.y + lane.h}" class="lane"/>'
        )
        cx, cy = lane.x + LANE_HEADER / 2, lane.cy
        out.append(_text(cx, cy, spec.role(role).label_fa, 12, extra=f' transform="rotate(-90 {cx:.0f} {cy:.0f})"'))

    # Flows first so shapes sit on top of line ends.
    for f in spec.flows:
        pts = geo.edges[f.name]
        d = " ".join(f"{x:.0f},{y:.0f}" for x, y in pts)
        out.append(f'<polyline points="{d}" class="flow" marker-end="url(#arrow)"/>')
        if f.is_default:  # BPMN default-flow slash near the source
            (ax, ay), (bx, by) = pts[0], pts[1]
            mx, my = ax + (8 if bx > ax else -8 if bx < ax else 0), ay + (8 if by > ay else -8 if by < ay else 0)
            out.append(f'<line x1="{mx - 5:.0f}" y1="{my + 5:.0f}" x2="{mx + 5:.0f}" y2="{my - 5:.0f}" class="flow"/>')
        if f.name in geo.edge_labels:
            out.append(_label_at(geo.edge_labels[f.name], f.label_fa))

    for n in spec.nodes:
        b = geo.nodes[n.name]
        if n.type in (NodeType.START, NodeType.END):
            cls = "event-end" if n.type == NodeType.END else "event"
            out.append(f'<circle cx="{b.cx:.0f}" cy="{b.cy:.0f}" r="{b.w / 2:.0f}" class="{cls}"/>')
            out.append(_text(b.cx, b.y + b.h + 12, n.label_fa, 11, cls="lbl"))
        elif n.type == NodeType.EXCLUSIVE_GATEWAY:
            pts = f"{b.cx:.0f},{b.y:.0f} {b.x + b.w:.0f},{b.cy:.0f} {b.cx:.0f},{b.y + b.h:.0f} {b.x:.0f},{b.cy:.0f}"
            out.append(f'<polygon points="{pts}" class="shape"/>')
            k = 8
            out.append(
                f'<path d="M{b.cx - k:.0f},{b.cy - k:.0f} L{b.cx + k:.0f},{b.cy + k:.0f} '
                f'M{b.cx + k:.0f},{b.cy - k:.0f} L{b.cx - k:.0f},{b.cy + k:.0f}" class="mark"/>'
            )
            if n.name in geo.node_labels:
                out.append(_label_at(geo.node_labels[n.name], n.label_fa))
        else:
            out.append(f'<rect x="{b.x:.0f}" y="{b.y:.0f}" width="{b.w:.0f}" height="{b.h:.0f}" rx="10" class="shape"/>')
            if n.type == NodeType.USER_TASK:  # small person glyph, top-left
                ix, iy = b.x + 12, b.y + 12
                out.append(
                    f'<circle cx="{ix:.0f}" cy="{iy - 2:.0f}" r="3.5" class="glyph"/>'
                    f'<path d="M{ix - 6:.0f},{iy + 9:.0f} a6,6 0 0 1 12,0" class="glyph"/>'
                )
            out.append(_multiline(b.cx, b.cy + 4, n.label_fa, 16))

    out.append("</svg>")
    return "".join(out)


SVG_CSS = """
.bpmn{display:block;width:100%;min-width:860px;height:auto}
.bpmn text{fill:var(--ink)}
.bpmn .lbl{fill:var(--muted)}
.bpmn .pool,.bpmn .lane{fill:none;stroke:var(--ink);stroke-width:1.2}
.bpmn .lane-alt{fill:var(--lane);stroke:none}
.bpmn .shape{fill:var(--card);stroke:var(--ink);stroke-width:1.6}
.bpmn .event{fill:var(--card);stroke:var(--ink);stroke-width:1.6}
.bpmn .event-end{fill:var(--card);stroke:var(--ink);stroke-width:4}
.bpmn .flow{fill:none;stroke:var(--ink);stroke-width:1.3}
.bpmn .arrowhead{fill:var(--ink)}
.bpmn .mark{stroke:var(--ink);stroke-width:3;stroke-linecap:round}
.bpmn .glyph{fill:none;stroke:var(--muted);stroke-width:1.3}
"""

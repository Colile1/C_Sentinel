"""
make_figures.py - draw the two Phase 2 figures as SVG, in the same visual style
as docs/diagrams/architecture.svg.

    python docs/diagrams/make_figures.py docs/diagrams

Writes phase2-architecture.svg and graph-model.svg. The PNGs embedded in the
report are screenshots of those SVGs (any browser's headless screenshot at 3x).

Author: Colile
"""

from __future__ import annotations

import sys
from html import escape
from pathlib import Path

INK, MUTED, RULE = "#1F2933", "#4A5568", "#B7C0CC"
FONT = 'font-family="Helvetica, Arial, sans-serif"'
DEFS = (
    '<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
    f'orient="auto-start-reverse"><path d="M 0 1 L 9 5 L 0 9 z" fill="{INK}"/></marker></defs>'
)


def text(x, y, value, size=9, fill=MUTED, anchor="start", weight=None, spacing=None):
    extra = f' font-weight="{weight}"' if weight else ""
    extra += f' letter-spacing="{spacing}"' if spacing else ""
    return (f'<text x="{x}" y="{y}" {FONT} font-size="{size}" fill="{fill}" '
            f'text-anchor="{anchor}"{extra}>{escape(value)}</text>')


def box(cx, cy, w, h, title, sub=None, fill="#FFFFFF"):
    parts = [f'<rect x="{cx - w / 2}" y="{cy - h / 2}" width="{w}" height="{h}" rx="3" '
             f'fill="{fill}" stroke="{INK}" stroke-width="1.2"/>']
    parts.append(text(cx, cy + (-2 if sub else 4), title, 11, INK, "middle"))
    if sub:
        parts.append(text(cx, cy + 13, sub, 9, MUTED, "middle"))
    return "".join(parts)


def arrow(points):
    path = " L ".join(f"{x} {y}" for x, y in points)
    return f'<path d="M {path}" fill="none" stroke="{INK}" stroke-width="1.1" marker-end="url(#a)"/>'


def group(x, y, w, h, label):
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="5" fill="#FCFCFD" stroke="{RULE}" '
            f'stroke-width="1" stroke-dasharray="5 3"/>' + text(x + 10, y + 15, label, 9, MUTED, spacing=0.7))


def svg(width, height, body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="#FFFFFF"/>'
            f'{DEFS}{"".join(body)}</svg>')


def architecture():
    body = [text(34, 77, "PHASE 1", spacing=0.7), text(34, 220, "SOC", spacing=0.7),
            text(34, 364, "GRAPH", spacing=0.7), text(34, 504, "RAG", spacing=0.7)]
    body.append(group(120, 24, 780, 96, "EVENT SOURCES"))
    emitters = [("Kong API Gateway", "401 / 403 / 429 via file-log"), ("auth-service", "FastAPI :8001"),
                ("incident-service", "FastAPI :8002"), ("asset-service", "FastAPI :8003"),
                ("Consul health checks", "critical checks, polled")]
    for index, (title, sub) in enumerate(emitters):
        body.append(box(201 + index * 154.5, 78, 142, 50, title, sub))
    body.append(arrow([(225, 120), (225, 186)]))
    body.append(text(237, 157, "JSON security events on stdout, plus health-check failures — one schema, docs/soc-events.md"))
    soc = [(225, "soc/collector", "reader + queryable EventStore"), (510, "soc/rules", "4 detection rules"),
           (795, "soc/alert_service", "alert store + REST API")]
    for cx, title, sub in soc:
        body.append(box(cx, 216, 190, 60, title, sub))
    body += [arrow([(320, 216), (415, 216)]), text(367, 209, "events", anchor="middle"),
             arrow([(605, 216), (700, 216)]), text(652, 209, "alerts", anchor="middle")]
    body += [arrow([(225, 246), (225, 290), (430, 290), (430, 330)]), text(327, 283, "events", anchor="middle"),
             arrow([(795, 246), (795, 290), (590, 290), (590, 330)]), text(692, 283, "alerts", anchor="middle")]
    body.append(box(220, 360, 180, 60, "Application topology", "services · endpoints · users · assets"))
    body.append(box(510, 360, 340, 60, "kg/loader → Neo4j knowledge graph", "12 node labels · 18 relationship types"))
    body.append(box(800, 360, 180, 60, "MITRE ATT&CK", "T1110, T1078, T1498, T1499"))
    body += [arrow([(310, 360), (340, 360)]), arrow([(710, 360), (680, 360)])]
    body += [arrow([(430, 390), (430, 432), (245, 432), (245, 470)]),
             text(337, 425, "6 Cypher queries (kg/cypher)", anchor="middle")]
    rag = [(245, "rag/retrieval", "intent → Cypher query → evidence rows"),
           (510, "rag/generation", "template, or optional LLM → answer + evidence"),
           (775, "Grounded answer", "nodes · relationships · documents · method")]
    for cx, title, sub in rag:
        body.append(box(cx, 500, 230, 60, title, sub))
    body += [arrow([(360, 500), (395, 500)]), arrow([(625, 500), (660, 500)])]
    return svg(920, 556, body)


def graph_model():
    c1, c2, c3, c4 = 150, 370, 590, 810
    r1, r2, r3, r4 = 60, 180, 300, 420
    topology, events, knowledge = "#EEF3FA", "#FDF3E7", "#EAF5EE"
    nodes = [
        (c1, r1, "Role", "name", topology), (c2, r1, "User", "username", topology),
        (c3, r1, "Endpoint", "path", topology), (c1, r4, "Asset", "name", topology),
        (c2, r2, "Event", "eventId", events), (c3, r2, "Service", "name", topology),
        (c1, r3, "Incident", "incidentId", events), (c2, r3, "Alert", "alertId", events),
        (c3, r3, "Threat", "techniqueId", knowledge), (c4, r3, "Vulnerability", "vulnId", knowledge),
        (c3, r4, "Control", "controlId", knowledge), (c4, r4, "Document", "docId", knowledge),
    ]
    body = [
        arrow([(308, 60), (212, 60)]), text(260, 53, "HAS_ROLE", anchor="middle"),
        arrow([(370, 82), (370, 158)]), text(363, 135, "TRIGGERED", anchor="end"),
        arrow([(405, 158), (405, 120), (560, 120), (560, 82)]), text(482, 113, "TARGETED", anchor="middle"),
        arrow([(432, 180), (528, 180)]), text(480, 173, "GENERATED_BY", anchor="middle"),
        arrow([(610, 158), (610, 82)]), text(617, 135, "EXPOSES"),
        arrow([(652, 168), (692, 168), (692, 192), (652, 192)]), text(700, 177, "DEPENDS_ON"),
        text(700, 190, "incident-service → asset-service"),
        arrow([(370, 202), (370, 278)]), text(377, 243, "CREATED_ALERT"),
        arrow([(212, 300), (308, 300)]), text(260, 293, "CONTAINS", anchor="middle"),
        arrow([(308, 190), (150, 190), (150, 278)]), text(158, 240, "CONCERNS"),
        arrow([(150, 322), (150, 398)]), text(158, 365, "AFFECTS"),
        arrow([(308, 170), (50, 170), (50, 420), (88, 420)]), text(56, 255, "ACCESSED"),
        arrow([(432, 300), (528, 300)]), text(480, 293, "INDICATES", anchor="middle"),
        arrow([(590, 278), (590, 202)]), text(583, 243, "TARGETS", anchor="end"),
        arrow([(652, 310), (748, 310)]), text(700, 324, "EXPLOITS", anchor="middle"),
        arrow([(630, 278), (630, 256), (676, 256), (676, 292), (652, 292)]), text(684, 262, "SUBTECHNIQUE_OF"),
        arrow([(570, 398), (570, 322)]), text(563, 366, "MITIGATES", anchor="end"),
        arrow([(748, 420), (652, 420)]), text(700, 413, "DESCRIBES", anchor="middle"),
        arrow([(810, 398), (810, 362), (625, 362), (625, 322)]),
        text(717, 355, "SUPPORTS_RESPONSE_TO", anchor="middle"),
    ]
    for cx, cy, title, key, fill in nodes:
        body.append(box(cx, cy, 124, 44, title, key, fill))
    legend = [(topology, "Application topology (Phase 1 structure)"),
              (events, "Events and alerts (Phase 2, live)"),
              (knowledge, "Security knowledge (MITRE ATT&CK, runbooks)")]
    body.append(text(250, 388, "SOURCE", spacing=0.7))
    for index, (fill, label) in enumerate(legend):
        y = 400 + index * 20
        body.append(f'<rect x="250" y="{y}" width="18" height="12" rx="2" fill="{fill}" stroke="{INK}" stroke-width="0.8"/>')
        body.append(text(276, y + 10, label))
    return svg(920, 470, body)


if __name__ == "__main__":
    out_dir = Path(sys.argv[1])
    (out_dir / "phase2-architecture.svg").write_text(architecture(), encoding="utf-8")
    (out_dir / "graph-model.svg").write_text(graph_model(), encoding="utf-8")
    print("Figures written: 2")

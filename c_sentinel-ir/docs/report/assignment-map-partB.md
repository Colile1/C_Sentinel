# Assignment map — Deliverable 1, Part B (the document)

Brief: `Submission Deliverable 1.pdf`. Deadline on the sheet: **5 September**. Student: Colile
Sibanda, 56543115. ITRI623, North-West University.

The document is graded directly under criterion 1 (15%) and is the artefact the marker reads
while watching the demo, so it also carries criteria 6 and 7 in written form.

| Part | Requirement (verbs verbatim) | Marks | Full-marks answer needs | Status |
|---|---|---|---|---|
| Header | "Name and student ID" | gate | Colile Sibanda + 56543115 on page 1, visible without scrolling | ☐ |
| B1 | "Brief description of system functionality (**one paragraph**)" | part of 15% | Exactly one paragraph. Names the three services, the gateway, what a user actually does end to end. No bullet list. | ☐ |
| B2a | "**All** endpoint URLs" | part of 15% | Every endpoint in the system listed **inside this document** — not a cross-reference to another file. 15 domain endpoints + 3 operational. | ☐ |
| B2b | "The base URL" | part of 15% | Base URL stated explicitly and formatted like the sheet's example | ☐ |
| B2c | "Specific endpoints such as `GET /v1/users`" | part of 15% | Method + full path per row, same shape as the sheet's example | ☐ |
| B2d | "Example requests and responses (**screenshots**) of one microservice" | part of 15% | Real screen captures of a live exchange against one service (incident-service). Request incl. headers, response incl. status + body. | ☐ |
| B3 | "Architecture diagram ... must be **professional** and show" 6 named elements | part of 15% ("architecture diagram is correct") | Diagram **embedded in the document**, showing: client/frontend, API Gateway, service registry, domain services, databases, the patterns applied. All six visibly labelled. | ☐ |
| B4 | "**List** the two patterns you implemented and **explain how you have implemented them**" | supports 10% | Both named; for each: what it is, the concrete implementation in this codebase (file/config), and why it holds. Gateway must NOT be claimed. | ☐ |
| B5 | "**Explain** how you are collecting security events" | supports 5% | Mechanism, not description: the emitting module, the fixed schema fields, correlation across services, and that it feeds Phase 2 | ☐ |
| Whole | "The document is **brief and to the point**" | 15% overall | Tight. No padding, no duplicated prose, no "see other file" deferrals for anything the sheet asks the document to show. | ☐ |

## Verbs that change the answer

- **"All endpoint URLs"** — the existing draft defers to `docs/api.md`. The marker opens *this*
  document. A deferral is a missing answer. Inline the full catalogue.
- **"screenshots"** — the sheet says screenshots, not code blocks. Capture live.
- **"professional and show ..."** — six elements are enumerated; each must be identifiable in the
  figure, and the figure must be *in* the document.
- **"explain how you have implemented"** — mechanism and location in the code, not a definition of
  the pattern.

## Risks carried into the audit

1. Deferral to other files (B2a, B3) — the single most likely way to lose the documentation mark.
2. Screenshots missing or not from a live run (B2d).
3. Section 1 written as more than one paragraph (B1 says one).
4. Patterns section drifting into definitions instead of implementation (B4).

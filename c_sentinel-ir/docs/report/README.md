# docs/report/

The submitted documents and the demo scripts, one set per phase. Written against each phase's
submission sheet section by section, because the sheets are explicit that an aspect not shown cannot
be marked.

## Phase 1 — Deliverable 1

| File | Responsibility |
|------|----------------|
| `deliverable1.md` | The submitted document, exported to PDF. Sections in the sheet's order: name and student number (Colile Sibanda, 56543115); system functionality in one paragraph; API documentation with base URL, endpoint list and example request/response screenshots for one microservice; architecture diagram; the two patterns and how each was implemented; how security events are collected |
| `demo-script.md` | The 8-10 minute demo, timed, in the sheet's mandated order, with the exact commands to run and the exact screens to open |
| `mark-map.md` | Each of the seven mark-schedule criteria mapped to the section, file and demo minute that earns it. Filled in at step 13 and used as the final pre-submission check |

## Phase 2

| File | Responsibility |
|------|----------------|
| `deliverable2.md` | The Phase 2 report, exported to PDF. Carries the "technical explanation" criterion (15%): architecture, design choices, limitations and the evidence index. Points at the three documents below rather than restating them |
| `detection-rules.md` | The rule catalogue the specification's §11.4 requires — all seven documented properties for each of the four rules, plus the design trap each rule exists to avoid. Five of the seven are printable from the code with `python -m soc.rules.main --catalogue` |
| `rag-demonstration.md` | The §11.6 demonstration — six question types and both refusal paths, each with the question, retrieved evidence, generated answer and retrieval method. Real captured output, not illustrative |
| `phase2-demo-script.md` | The Phase 2 demo, timed, built around `scripts/run_security_workflow.py` so the §7 workflow scenario runs in one pass on camera |
| `mark-map-phase2.md` | The seven Phase 2 assessment criteria mapped to artefact, build step and demo minute. The final pre-submission check |

The graph model the specification's §11.3 requires is not here: it lives with the code it describes,
at `kg/model/graph_model.md`, so a test can cross-check it against `graph_model.py` and the loaders.

## The Phase 1 demo order — non-negotiable

The sheet fixes the sequence, and marks are lost by wandering off it:

1. Camera on, identify yourself, then camera off.
2. One complete business workflow from the client.
3. The gateway: configuration, and evidence of live routing read off the endpoint addresses.
4. The registry: registered instances and their addresses.
5. Proof Docker hosts the services.
6. The two patterns: code or configuration, *and* proof they work in the application.
7. How security events are captured, for the next deliverable.

Point 6 is where projects lose marks quietly. Showing the circuit-breaker code is not proof — the
breaker opening on camera while `asset-service` is stopped is.

## The Phase 2 demo — one workflow, one pass

Phase 2's specification does not fix a sequence; it fixes a **scenario** (§7), and the scenario must
run end to end without stitching: failed logins → collected events → detection rule → alert → Neo4j
→ linked to user, service, endpoint and threat → threat to controls → a natural-language question →
a grounded answer with its evidence.

That is why `scripts/run_security_workflow.py` exists. Running four CLIs by hand on camera invites
one of them to fail halfway and take the narration with it; one command that stops at the first
failing stage and names it does not.

The quiet mark-loser here is the **evidence block**, not the answer. §5.3 requires every answer to
display retrieved nodes, retrieved relationships, source documents and the retrieval method. Reading
the generated prose and scrolling past the evidence gives away the largest criterion on the sheet.

Done when: both mark maps have no empty row, a timed rehearsal of `demo-script.md` lands between 8
and 10 minutes, and `python scripts/run_security_workflow.py` completes all four stages with exit 0.

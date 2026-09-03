# docs/report/

The submitted document and the demo script. Written against the Deliverable 1 submission sheet
section by section, because the sheet is explicit that an aspect not shown cannot be marked.

| File | Responsibility |
|------|----------------|
| `deliverable1.md` | The submitted document, exported to PDF. Sections in the sheet's order: name and student number (Colile Sibanda, 56543115); system functionality in one paragraph; API documentation with base URL, endpoint list and example request/response screenshots for one microservice; architecture diagram; the two patterns and how each was implemented; how security events are collected |
| `demo-script.md` | The 8-10 minute demo, timed, in the sheet's mandated order, with the exact commands to run and the exact screens to open |
| `mark-map.md` | Each of the seven mark-schedule criteria mapped to the section, file and demo minute that earns it. Filled in at step 13 and used as the final pre-submission check |

## The demo order — non-negotiable

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

Done when: `mark-map.md` has no empty row, and a timed rehearsal of `demo-script.md` lands between
8 and 10 minutes.

# tests/contract/

The tests that stop the two shared contracts from drifting. These are cheap to write and they are
what prevents a Phase 2 rewrite.

| File | Responsibility |
|------|----------------|
| `test_event_schema.py` | Every `eventType` in `docs/soc-events.md` is defined in `EventType`; a valid event round-trips through JSON unchanged; an event with an unknown extra field is rejected; an event missing a required field raises rather than emitting |
| `test_event_emission.py` | Parses a captured log sample from each service and asserts every line carrying `eventType` validates as a `SecurityEvent`. This is the test that catches a service inventing its own log format |
| `test_error_shape.py` | Every error raised by `libs/common/errors.py` maps to the documented status code and serialises to the single documented error shape |

Done when: renaming a field in `SecurityEvent` without updating `docs/soc-events.md` fails a test.

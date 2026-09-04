# soc/rules/ — **Phase 2**

The detection rules. The specification requires at least three, and requires each to document its
rule name, purpose, input events, detection logic, severity, generated alert and suggested response
action — so the rule and its documentation are the same artefact. Six of those seven are attributes
on the rule class and the seventh is `evaluate`'s body, which means a rule cannot be written without
stating all seven, and `python -m soc.rules.main --catalogue` prints the catalogue straight from the
code rather than from a document that can drift away from it.

## Files

| File | Rule |
|------|------|
| `base.py` | `DetectionRule` — the interface every rule implements: `name`, `purpose`, `input_event_types`, `severity`, `recommended_action`, `evaluate(store, now) -> list[Alert]`, and the shared `build_alert` helper. Rules are pure functions of the store's contents and a clock, so they are testable without containers |
| `rule_failed_logins.py` | **Multiple Failed Logins.** Five `AUTH_FAILED` events for the same user *or* the same source IP within five minutes. HIGH. Action: temporarily block the source IP and verify whether the account is compromised |
| `rule_unauthorised_access.py` | **Unauthorised Endpoint Access.** Three refusals (401/403) from one subject within ten minutes. MEDIUM, rising to HIGH on the privileged `/api/v1/auth/users` route. Action: review the role assignment and audit the endpoint |
| `rule_abnormal_rate.py` | **Abnormal Request Rate.** One source exceeding 30 requests in a minute, *or* three `RATE_LIMIT_EXCEEDED` events from the gateway. HIGH. Action: rate-limit the source and check upstream capacity |
| `rule_service_failure.py` | **Service Failure.** Any `CIRCUIT_OPENED`, or three `DEPENDENCY_FAILURE` / `SERVICE_ERROR` events from one service in five minutes. HIGH. Action: check the dependency and the breaker state |
| `catalogue.py` | `all_rules()` — the registry every consumer iterates; `evaluate_all(store, now)` — run the whole catalogue in one pass |
| `main.py` | `python -m soc.rules.main [--file PATH \| --stdin] [--now TS] [--catalogue]` — collect, evaluate, report. Reuses the collector's source selection |
| `tests/` | Each rule tested in both directions: it fires on the scripted attack, and it stays silent on a normal `demo_workflow` run. A rule that never sleeps is as useless as one that never fires |

## The two directions, and why both are tested

`tests/conftest.py` holds one `normal_workflow_store` — a clean demo run, plus one mistyped password
and one expired-token bounce — and every rule asserts silence against it. `test_catalogue.py` then
asserts the whole catalogue is silent on it in one pass, and `tests/test_main.py` re-runs that
silence check against `docs/evidence/step12-correlated-logs.jsonl`, which is a **real** capture taken
off the running stack at step 12. Passing against data written for the test proves less than passing
against data the system actually produced.

## Design notes worth keeping

- **Rule 1 keys on both user and source IP, and a burst tripping both raises two alerts.** They are
  different findings — "this account is under attack" and "this address is attacking" — and a
  responder acts on each differently. See D-26.
- **Rule 2 excludes `AUTH_FAILED` although it carries a 401.** A rejected password is an
  *authentication* failure and belongs to Rule 1; counting it here would make every brute-force run
  fire two rules for one attack.
- **Rule 2 also reads plain 401/403 events, not only `UNAUTHORISED_ACCESS`.** A 403 raised inside a
  service by `require_admin` never reaches the gateway plugin, and missing it would leave the rule
  blind to exactly the privilege-escalation attempt it exists to catch.
- **Rule 3 fires on gateway refusals alone.** Kong absorbs a burst before it reaches a service, so
  the events that prove the attack are 429s, not a pile of `REQUEST_RECEIVED`. A volume-only rule
  would stay silent through the very scenario it is written for. See D-27.
- **Rule 4 fires on one `CIRCUIT_OPENED` with no threshold, and never on `CIRCUIT_CLOSED`.** The
  breaker opens only after the configured number of whole failed requests, each having exhausted its
  retries (D-16), so the judgement has already been made. A recovery that raised an alarm would
  train the responder to ignore the ones that matter.

## Running it

```bash
python scripts/capture_attack_evidence.py                       # write the scripted attack
python -m soc.rules.main --file docs/evidence/step15-attack-events.jsonl
python -m soc.rules.main --catalogue                            # the rule catalogue
python -m soc.rules.main                                        # the running stack's logs
python -m pytest soc                                            # the tests
```

## Integration

Reads `soc/collector`'s store. Raises `soc.alert_service.models.Alert`; step 16 adds the store and
API that persist and serve them. Imports no Phase 1 service.

Done when: all three required rules fire on their scripted attacks and none fires on a clean
workflow run. **Met** — see `docs/evidence/step15-detection-run.txt`.

# soc/rules/ — **Phase 2**

The detection rules. The specification requires at least three, and requires each to document its
rule name, purpose, input events, detection logic, severity, generated alert and suggested response
action — so the rule and its documentation are the same artefact.

## Planned files

| File | Rule |
|------|------|
| `base.py` | `DetectionRule` — the interface every rule implements: `name`, `purpose`, `input_event_types`, `severity`, `evaluate(store, now) -> list[Alert]`, `recommended_action`. Rules are pure functions of the store's contents and a clock, so they are testable without containers |
| `rule_failed_logins.py` | **Multiple Failed Logins.** Five `AUTH_FAILED` events for the same user or source IP within five minutes. HIGH. Action: temporarily block the source IP and verify whether the account is compromised |
| `rule_unauthorised_access.py` | **Unauthorised Endpoint Access.** Repeated 401 or 403 responses on protected endpoints from one user. MEDIUM, rising to HIGH on a protected admin route. Action: review the user's role assignment and audit the endpoint |
| `rule_abnormal_rate.py` | **Abnormal Request Rate.** A service receiving requests far above its baseline in a short window, including `RATE_LIMIT_EXCEEDED` from the gateway. `POSSIBLE_DOS`. Action: rate-limit the source and check upstream capacity |
| `rule_service_failure.py` | **Service Failure.** Repeated `SERVICE_ERROR`, `DEPENDENCY_FAILURE` or `CIRCUIT_OPENED`, or a failing health check. `SERVICE_FAILURE`. Action: check the dependency and the breaker state. *(Optional fourth — it comes nearly free from the Phase 1 breaker events)* |
| `catalogue.py` | `all_rules() -> list[DetectionRule]` — the registry the runner iterates |
| `tests/` | Each rule tested in both directions: it fires on the scripted attack, and it stays silent on a normal `demo_workflow` run. A rule that never sleeps is as useless as one that never fires |

## Integration

Reads `soc/collector`'s store. Writes alerts through `soc/alert-service`. Imports no Phase 1 service.

Done when: all three required rules fire on their scripted attacks and none fires on a clean
workflow run.

# Detection rule catalogue — Sentinel-IR

The Phase 2 specification (§3.3 and §11.4) requires seven documented properties per rule: name,
purpose, input events, detection condition, severity, generated alert, and recommended response.
This document states all seven for each of the four rules.

**Five of the seven are read out of the code, not restated from it.** `DetectionRule` in
[soc/rules/base.py](../../soc/rules/base.py) declares `name`, `purpose`, `input_event_types`,
`severity` and `recommended_action` as class attributes, so a rule cannot be written without
stating them, and

```bash
python -m soc.rules.main --catalogue
```

prints them straight from the classes. The sixth — the detection condition — is `evaluate`'s body,
so it is written out in prose below, next to the constants that fix its thresholds. The seventh,
the generated alert, is shown as the alert the rule actually raised on the committed attack capture.

The specification names three rules as the minimum. Four are built: the three it names, plus
**Service Failure**, which comes nearly free off the Phase 1 circuit-breaker events and shows the
marked resilience pattern feeding the SOC layer.

## Summary

| # | Rule | Input events | Window | Threshold | Severity |
|---|------|--------------|--------|-----------|----------|
| 1 | Multiple Failed Logins | `AUTH_FAILED` | 5 minutes | 5 per subject | HIGH |
| 2 | Unauthorised Endpoint Access | `UNAUTHORISED_ACCESS`, any 401/403 | 10 minutes | 3 per subject | MEDIUM, HIGH on a privileged route |
| 3 | Abnormal Request Rate | `RATE_LIMIT_EXCEEDED`, `REQUEST_RECEIVED` | 1 minute | 3 refusals **or** 30 requests per source | HIGH |
| 4 | Service Failure | `CIRCUIT_OPENED`, `DEPENDENCY_FAILURE`, `SERVICE_ERROR` | 5 minutes | 1 opened circuit **or** 3 failures | HIGH |

---

## Rule 1 — Multiple Failed Logins

[soc/rules/rule_failed_logins.py](../../soc/rules/rule_failed_logins.py)

| Property | Value |
|----------|-------|
| **Purpose** | Detect a brute-force or credential-stuffing attempt against the authentication endpoint before an account is compromised. |
| **Input events** | `AUTH_FAILED` |
| **Detection condition** | Five or more `AUTH_FAILED` events for the same subject within a five-minute window. The subject is keyed **two ways** — by `userId` and by `sourceIp` — and each key is counted independently. |
| **Severity** | HIGH |
| **Generated alert** | `Multiple Failed Logins`, citing every failed-login event in the window as `relatedEvents`, with `affectedService` = `auth-service` and `affectedEntity` = `login-endpoint`. |
| **Recommended response** | Temporarily block the source IP at the gateway and verify whether the targeted account is compromised; force a password reset if it is. |

**Why the subject is keyed twice.** An attacker controls one of the two identifiers but rarely both.
Keying only on `userId` misses a run that invents a fresh username each attempt; keying only on
`sourceIp` misses a distributed run against one account. A burst that trips both raises **two**
alerts deliberately: "this account is under attack" and "this address is
attacking" are different findings with different responses.

**Why the rule can see attacks on accounts that never existed.** `auth_service.py` emits
`AUTH_FAILED` on *every* failure path including an unknown username, recording the attempted name
as the `userId`. That was fixed at build step 5 (D-11) precisely so this rule is not blind to it.

---

## Rule 2 — Unauthorised Endpoint Access

[soc/rules/rule_unauthorised_access.py](../../soc/rules/rule_unauthorised_access.py)

| Property | Value |
|----------|-------|
| **Purpose** | Detect a caller probing endpoints outside its authorisation — reconnaissance, or a stolen token being tested for reach. |
| **Input events** | `UNAUTHORISED_ACCESS` from the gateway, plus any event carrying a 401 or 403 status code. `AUTH_FAILED` is **excluded**. |
| **Detection condition** | Three or more refusals (status 401 or 403) for the same subject within a ten-minute window. |
| **Severity** | MEDIUM, escalating to HIGH when any refusal landed on a privileged route (`/api/v1/auth/users`, the one endpoint set behind `require_admin` in Phase 1). |
| **Generated alert** | `Unauthorised Endpoint Access`, naming the count, the subject, the number of distinct endpoints and any privileged route among them; `affectedEntity` is the privileged route where one was probed. |
| **Recommended response** | Review the subject's role assignment, audit the endpoints it was refused on, and revoke the token if the access pattern is not explainable by a legitimate client. |

**Why the threshold is lower than Rule 1's.** A failed login is a routine typo; an authorisation
refusal on a protected route is not. Three in ten minutes is already a pattern.

**Why `AUTH_FAILED` is excluded.** An `AUTH_FAILED` event carries a 401, so a naive "count the 401s"
rule would fire this rule on every Rule 1 attack — two alerts for one attack, and doubled responder
work. The exclusion is explicit and regression-tested by
`test_failed_logins_are_left_to_rule_one`.

**Why in-service refusals are read, not only gateway ones.** A 403 raised inside a service — an
analyst hitting an admin route with a perfectly valid token — never reaches Kong's plugin. Reading
only gateway events would leave the rule blind to exactly the privilege-escalation attempt it exists
to catch.

---

## Rule 3 — Abnormal Request Rate

[soc/rules/rule_abnormal_rate.py](../../soc/rules/rule_abnormal_rate.py)

| Property | Value |
|----------|-------|
| **Purpose** | Detect a possible denial-of-service attempt, runaway client or automated scan driving request volume far above the working rate. |
| **Input events** | `RATE_LIMIT_EXCEEDED`, `REQUEST_RECEIVED` |
| **Detection condition** | Within a one-minute window, per **source address**: three or more `RATE_LIMIT_EXCEEDED` events, **or** thirty or more requests received. Either signal alone is sufficient. |
| **Severity** | HIGH |
| **Generated alert** | `Abnormal Request Rate`, naming every signal that fired and citing all the events behind them; `affectedEntity` is the offending source address. |
| **Recommended response** | Rate-limit or block the source address at the gateway, then check upstream capacity and confirm the affected services recovered. |

**Why two independent signals (D-27).** Kong's global rate limit refuses a burst *before* it reaches
a service, so the surviving evidence of the demo's flood is 429s, not a pile of `REQUEST_RECEIVED`.
A volume-only rule would stay silent through the very scenario it is written for. The gateway
refusal signal exists because the infrastructure has already made the judgement that a client
crossed the limit — a rule that ignored its own gateway saying so would detect the attack more
slowly than the gateway already did.

**Why volume is measured per source, not per service.** A service under load from fifty legitimate
analysts is busy; one address producing the same volume is not. Measuring per service would mistake
a popular service for one under attack.

**Why thirty requests.** Kong's own limit is 60 per minute (`gateway/kong.yml`), so a source seen
making more than thirty in a minute is already at half the gateway's ceiling.

---

## Rule 4 — Service Failure

[soc/rules/rule_service_failure.py](../../soc/rules/rule_service_failure.py)

| Property | Value |
|----------|-------|
| **Purpose** | Detect a service losing a dependency or returning server errors, so the outage is investigated before it reaches every caller. |
| **Input events** | `CIRCUIT_OPENED`, `DEPENDENCY_FAILURE`, `SERVICE_ERROR`. `CIRCUIT_CLOSED` is read but never fires the rule. |
| **Detection condition** | Within a five-minute window, per service: **any** `CIRCUIT_OPENED` event — no threshold — **or** three or more `DEPENDENCY_FAILURE` / `SERVICE_ERROR` events. |
| **Severity** | HIGH |
| **Generated alert** | `Service Failure`, naming the failing service and which signal fired; a `CIRCUIT_CLOSED` in the window annotates the description with the recovery but does not suppress the alert. |
| **Recommended response** | Check the health of the failing dependency and the circuit breaker's state, confirm the documented fallback is being served, and restart the dependency if it is down. |

**Why an opened circuit needs no threshold.** The breaker in `libs/common/http_client.py` opens only
after the configured number of *whole* requests failed, each having exhausted its retries first
(D-16). By the time `CIRCUIT_OPENED` is emitted the system has independently established that a
dependency is down. Requiring this rule to see that happen three more times would delay the alert
past the point where it is useful.

**Why recovery never fires it.** `CIRCUIT_CLOSED` is read only to note recovery in the description.
An alarm on recovery trains the responder to ignore the ones that matter.

**This rule is the optional fifth in the specification's list**, built because it costs almost
nothing: the Phase 1 circuit breaker already emits exactly the events it needs, so it is the point
where one of the two marked Phase 1 patterns feeds the Phase 2 SOC layer directly.

---

## Verification — both directions

The build order's step-15 verification is that each rule fires on a scripted attack **and stays
silent on the normal workflow**. Both halves are tested, and the silent half twice:

```bash
python scripts/capture_attack_evidence.py                                    # 22-event attack
python -m soc.rules.main --file docs/evidence/step15-attack-events.jsonl     # 5 alerts, all 4 rules
python -m soc.rules.main --file docs/evidence/step12-correlated-logs.jsonl   # 0 alerts
```

The attack is one story in order: an attacker brute-forces an analyst account, gets in, probes
endpoints its role does not cover including the admin route, then floods the gateway until the rate
limiter refuses it and `asset-service` falls over behind the breaker. It raises **five alerts from
all four rules** — Rule 1 twice, once per key.

The silent direction is checked against a hand-built clean workflow fixture *and* against
`docs/evidence/step12-correlated-logs.jsonl`, a **real 16-event capture taken off the running stack
at build step 12**. Passing against data written for the test proves less than passing against data
the system actually produced.

Captured output: [docs/evidence/step15-detection-run.txt](../evidence/step15-detection-run.txt).
**89 unit tests** cover `soc/`, none needing a container, a network or a database.

## Where the alerts go next

Every alert raised is stored by `soc/alert_service` and served over
`GET /api/v1/alerts`. `soc.rules.main` refuses to store an alert whose `relatedEvents` do not all
resolve to real events in the collector's store — an alert citing evidence that does not exist is an
assertion, not a finding. From there `kg/loader/load_events.py` writes each alert into Neo4j and
links it: `(:Event)-[:CREATED_ALERT]->(:Alert)-[:INDICATES]->(:Threat)`, which is what makes the
rules reachable from the RAG layer's questions.

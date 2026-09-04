# Knowledge graph model — Sentinel-IR

The Neo4j security knowledge graph. Twelve node labels over three sources of knowledge —
what the application **is**, what **happened** in it, and what is **known** about the
threats those happenings suggest — connected by fourteen relationship types.

This document and [`graph_model.py`](graph_model.py) are the same model. The loaders in
`kg/loader/` build exactly the labels and relationships listed here; `schema.cypher` puts a
uniqueness constraint on each label's natural key. `kg/loader/tests/` asserts there is no
drift between the three.

## Node labels

| Label | Natural key | Key properties | Source | Participates in |
|-------|-------------|----------------|--------|-----------------|
| `User` | `username` | `username`, `role` | topology (from auth-service accounts) | `-[:TRIGGERED]->(:Event)`, `-[:HAS_ROLE]->(:Role)` |
| `Role` | `name` | `name` | topology | `(:User)-[:HAS_ROLE]->`, `(:Document)` n/a |
| `Service` | `name` | `name`, `port`, `description` | topology (Compose + registry) | `-[:DEPENDS_ON]->(:Service)`, `-[:EXPOSES]->(:Endpoint)`, `(:Event)-[:GENERATED_BY]->`, `(:Threat)-[:TARGETS]->` |
| `Endpoint` | `path` | `path`, `method`, `protected` | topology (gateway routes) | `(:Service)-[:EXPOSES]->`, `(:Event)-[:TARGETED]->` |
| `Asset` | `name` | `name`, `assetType`, `criticality` | topology (asset-service register) | — (held for completeness of the application picture) |
| `Event` | `eventId` | every key in `docs/soc-events.md` | events (`soc/collector`) | `(:User)-[:TRIGGERED]->`, `-[:GENERATED_BY]->(:Service)`, `-[:TARGETED]->(:Endpoint)`, `-[:CREATED_ALERT]->(:Alert)` |
| `Alert` | `alertId` | every key in the alert schema | events (`soc/alert_service`) | `(:Event)-[:CREATED_ALERT]->`, `-[:INDICATES]->(:Threat)`, `(:Incident)-[:CONTAINS]->` |
| `Incident` | `incidentId` | `incidentId`, `title`, `severity`, `status` | events (incident-service, optional) | `-[:CONTAINS]->(:Alert)` |
| `Threat` | `techniqueId` | `techniqueId`, `name`, `tactic`, `description` | security knowledge (MITRE ATT&CK) | `(:Alert)-[:INDICATES]->`, `-[:TARGETS]->(:Service)`, `-[:EXPLOITS]->(:Vulnerability)`, `-[:SUBTECHNIQUE_OF]->(:Threat)`, `(:Control)-[:MITIGATES]->`, `(:Document)-[:SUPPORTS_RESPONSE_TO]->` |
| `Control` | `controlId` | `controlId`, `name`, `description` | security knowledge | `-[:MITIGATES]->(:Threat)`, `(:Document)-[:DESCRIBES]->` |
| `Vulnerability` | `vulnId` | `vulnId`, `name`, `description` | security knowledge | `(:Threat)-[:EXPLOITS]->` |
| `Document` | `docId` | `docId`, `title`, `kind` | security knowledge (response procedures) | `-[:DESCRIBES]->(:Control)`, `-[:SUPPORTS_RESPONSE_TO]->(:Threat)` |

## Relationship types

```
(:User)-[:TRIGGERED]->(:Event)                  a user's action produced an event
(:Event)-[:GENERATED_BY]->(:Service)            the service that emitted the event
(:Event)-[:TARGETED]->(:Endpoint)               the endpoint the event was about
(:Event)-[:CREATED_ALERT]->(:Alert)             an event a detection rule cited as evidence
(:Alert)-[:INDICATES]->(:Threat)                the ATT&CK technique the alert's rule detects
(:Threat)-[:TARGETS]->(:Service)                the service the technique is aimed at
(:Threat)-[:EXPLOITS]->(:Vulnerability)         the weakness the technique relies on
(:Threat)-[:SUBTECHNIQUE_OF]->(:Threat)         a MITRE sub-technique to its parent (T1110.00x -> T1110)
(:Control)-[:MITIGATES]->(:Threat)              a countermeasure against the technique
(:Incident)-[:CONTAINS]->(:Alert)               an incident groups the alerts under it
(:Service)-[:DEPENDS_ON]->(:Service)            the real incident-service -> asset-service call
(:Service)-[:EXPOSES]->(:Endpoint)              a route the gateway publishes for the service
(:User)-[:HAS_ROLE]->(:Role)                    the account's authorisation role
(:Document)-[:DESCRIBES]->(:Control)            a procedure that documents a control
(:Document)-[:SUPPORTS_RESPONSE_TO]->(:Threat)  a runbook for responding to the technique
```

## The three sources

1. **Application topology** — `load_topology.py`. Services and their ports, the endpoints each
   exposes and whether the gateway protects them, the one real `incident-service -[:DEPENDS_ON]->
   asset-service` edge, the asset register, and the seeded user accounts with their roles.
2. **Live events and alerts** — `load_events.py`. Every `SecurityEvent` the collector holds and
   every `Alert` the rules raised, wired with `TRIGGERED`, `GENERATED_BY`, `TARGETED` and
   `CREATED_ALERT`. `CREATED_ALERT` is built from the alert's `relatedEvents`, which is why that
   list may not be empty.
3. **Security knowledge** — `load_security_knowledge.py`. MITRE ATT&CK **T1110 Brute Force** and
   its sub-techniques T1110.001–T1110.004, the weakness they exploit, and the controls that
   mitigate them — account lockout, multi-factor authentication and password reset — plus the
   response runbooks. `INDICATES` links the *Multiple Failed Logins* rule's alerts to T1110, so a
   failed-login alert reaches a control in three hops:
   `(:Alert)-[:INDICATES]->(:Threat)<-[:MITIGATES]-(:Control)`.

## Diagram

```
                 ┌────────┐  HAS_ROLE   ┌──────┐
                 │  User  │────────────▶│ Role │
                 └───┬────┘             └──────┘
                     │ TRIGGERED
                     ▼
   GENERATED_BY  ┌────────┐  TARGETED   ┌──────────┐  EXPOSES   ┌─────────┐
 ┌──────────────│  Event │────────────▶│ Endpoint │◀───────────│ Service │
 │              └───┬────┘             └──────────┘            └────┬────┘
 ▼                  │ CREATED_ALERT                DEPENDS_ON  ┌────┘ │ TARGETS (from Threat)
┌─────────┐         ▼                              (self)     ▼      ▼
│ Service │◀── ┌────────┐  INDICATES   ┌────────┐  TARGETS   ┌─────────┐
└─────────┘    │ Alert  │────────────▶│ Threat │───────────▶│ Service │
   ▲           └───┬────┘             └───┬─┬──┘            └─────────┘
   │ CONTAINS      │                      │ │ EXPLOITS
┌──┴──────┐        │              MITIGATES │ ▼
│Incident │        │            ┌─────────┐ │ ┌───────────────┐
└─────────┘        │            │ Control │─┘ │ Vulnerability │
                   │            └────┬────┘   └───────────────┘
                   │        DESCRIBES │            ▲
                   │        ┌─────────┴──┐         │ EXPLOITS
                   └───────▶│  Document  │─────────┘ (Threat→Vuln)
              SUPPORTS_      └────────────┘
              RESPONSE_TO
```

Done when: `schema.cypher` applies cleanly to an empty database, `python -m kg.loader.main`
produces a graph holding every label above, a topology query returns
`incident-service -[:DEPENDS_ON]-> asset-service`, and T1110 with its controls is reachable
from a *Multiple Failed Logins* alert in three hops.

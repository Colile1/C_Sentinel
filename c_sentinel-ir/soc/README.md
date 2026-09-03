# soc/ — **Phase 2**

The Security Operations Centre layer: collect the events Phase 1 already emits, detect suspicious
patterns in them, and raise alerts. Do not build here until Deliverable 1 is submitted, but do not
weaken its assumptions either — every design choice in Phase 1's event schema exists to make this
folder buildable.

## Subfolders

| Folder | Purpose |
|--------|---------|
| `collector/` | Reads the event stream and stores it queryably |
| `rules/` | The detection rules, one file per rule |
| `alert-service/` | The alert model, store and API |

## The required event sources

The specification names four, and all four already exist in Phase 1: the API Gateway (Kong's log
plugin), the auth service, at least two domain services, and container health information from
Consul and the `/health` endpoints.

## Dependency direction

`soc` imports `libs/common` for the event schema and nothing else. No Phase 1 service imports `soc`.
Events flow one way: services emit, the collector consumes.

Done when: a scripted attack produces events from all four sources, three rules fire on it, and each
firing creates an alert in the specification's schema.

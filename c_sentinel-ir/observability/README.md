# observability/

Logs, metrics and health — the data the system produces about itself. In Phase 1 this earns the
observability half of the non-functional requirements and feeds the 5% "preparation for SOC" mark.
In Phase 2 it becomes the raw material the SOC layer consumes.

These are supporting patterns, not the two claimed for the pattern mark. See `docs/patterns.md`.

## Subfolders

| Folder | Purpose |
|--------|---------|
| `prometheus/` | `prometheus.yml` — scrape configuration targeting the `/metrics` endpoint of all three services and the gateway |
| `grafana/` | `datasource.yml` provisioning Prometheus, and `dashboards/sentinel.json` — request rate, error rate, latency, authentication failures, incidents created |
| `logging/` | `README.md` explaining the centralised logging approach, plus `log_query_examples.md` — the exact commands used on camera to show correlated events |

## The centralised logging approach

Every service writes newline-delimited JSON to stdout through `libs/common/logging.py`. Docker
collects stdout, so `docker compose logs` is already a central view across all services with no
extra infrastructure. Because every line carries `correlationId`, one workflow is retrievable
across three services with a single grep — and because every security-relevant line is a
`SecurityEvent`, the same stream is machine-readable input for Phase 2's collector.

The specification lists Seq, ELK and Loki as options. Docker logs is explicitly acceptable, and it
has the advantage of being demonstrable in one command rather than needing a second stack to be
healthy on camera. The report states this choice and its trade-off rather than implying an
aggregation tool is present.

## Metrics that matter

The specification names the useful ones and they map directly onto Phase 2's detection rules:
request count, failed request count, response time, records created, and authentication failures.
The Grafana dashboard shows exactly these five, because a dashboard of things nobody asked for is
harder to explain in a ten-minute demo than one that answers the brief line by line.

## Integration

Prometheus scrapes the services; nothing in the services depends on Prometheus being up. Grafana
reads Prometheus only. In Phase 2, `soc/collector` reads the same log stream Docker already
collects — it does not replace this folder, it consumes it.

Done when: all Prometheus targets are UP, the dashboard renders live data from a demo run, and one
`docker compose logs | grep <correlation-id>` returns the events from all three services.

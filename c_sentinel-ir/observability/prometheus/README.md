# observability/prometheus/

Prometheus scrape configuration.

| File | Responsibility |
|------|----------------|
| `prometheus.yml` | Global scrape interval, and one job per target: auth-service, incident-service, asset-service and the Kong gateway, each scraped on its `/metrics` path over the Compose network |

Services expose metrics through `prometheus-fastapi-instrumentator`, mounted in each service's
`app/main.py`. Prometheus is scraped by Grafana and by nothing else.

Done when: `localhost:9090/targets` shows every target UP after `docker compose up`.

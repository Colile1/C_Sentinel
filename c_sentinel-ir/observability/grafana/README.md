# observability/grafana/

Grafana provisioning — datasource and dashboard as code, so the dashboard survives a container
rebuild and can be committed and marked.

| File | Responsibility |
|------|----------------|
| `datasource.yml` | Provisions Prometheus as the default datasource at its Compose address |
| `dashboards/sentinel.json` | The five panels the specification asks for: request count, failed requests, response time, records created, authentication failures |
| `dashboards/dashboard-provider.yml` | Tells Grafana where to find the dashboard JSON |

Anonymous viewer access is enabled in Compose so the demo does not spend thirty seconds on a login
screen; the admin password still comes from `deploy/.env`.

Done when: `localhost:3000` opens straight onto the dashboard and the panels show data produced by
`python client/demo_workflow.py`.

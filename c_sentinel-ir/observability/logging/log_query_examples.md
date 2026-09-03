# Centralised logging - the exact commands used on camera

Every service writes one JSON object per line to stdout through
`libs/common/logging.py`. Docker collects stdout, so `docker compose logs` is
already a single view across all services - no Seq, no ELK, no Loki container to
keep healthy on camera. Operational lines carry `level`, `service`, `timestamp`,
`message`, `correlationId`; security-relevant lines are a full `SecurityEvent`
and additionally carry `eventType`, which is the field Phase 2's collector
filters on.

Run these from the repository root with the stack up
(`docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d`).

## 1. Follow every service at once

```bash
docker compose -f deploy/docker-compose.yml logs -f --tail=20 \
  auth-service incident-service asset-service
```

## 2. One workflow across three services, by correlation ID

Run the demo, grab the correlation ID it prints, then:

```bash
CID=<the id from client/demo_workflow.py>
docker compose -f deploy/docker-compose.yml logs --no-log-prefix \
  auth-service incident-service asset-service \
  | grep "$CID" \
  | jq -c '{t: .timestamp, svc: .service, msg: .message, evt: .eventType}'
```

One login, one incident create, one asset lookup - three services, one thread.

## 3. Only the authentication failures

```bash
docker compose -f deploy/docker-compose.yml logs --no-log-prefix auth-service \
  | jq -c 'select(.eventType == "AUTH_FAILED") | {t: .timestamp, userId, sourceIp, correlationId}'
```

## 4. A circuit-breaker state change

With `asset-service` stopped (`docker compose ... stop asset-service`) and a few
incidents created so the breaker trips:

```bash
docker compose -f deploy/docker-compose.yml logs --no-log-prefix incident-service \
  | jq -c 'select(.eventType | test("^CIRCUIT_")) | {t: .timestamp, eventType, message}'
```

## 5. Every line is valid JSON

The claim the contract rests on - no service prints, no line is hand-formatted:

```bash
docker compose -f deploy/docker-compose.yml logs --no-log-prefix \
  auth-service incident-service asset-service \
  | jq -e . > /dev/null && echo "Description: all log lines parsed as JSON"
```

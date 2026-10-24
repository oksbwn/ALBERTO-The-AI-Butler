# Operations, Monitoring & Maintenance

This guide covers operational monitoring, logging, upgrades, and routine maintenance of a running Alberto system.

---

## 1. Health Checks & Diagnostics

Alberto exposes two diagnostic endpoints for infrastructure monitoring:

### Liveness Probe
`GET /health`
Returns `HTTP 200` with basic process status:
```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

### Readiness & Diagnostics Probe
`GET /v1/health/diagnostics` (requires admin token)
Returns detailed subsystem status:
```json
{
  "database": { "status": "connected", "engine": "sqlite" },
  "checkpointer": { "status": "ready", "backend": "sqlite" },
  "vector_store": { "status": "ready", "collections_count": 2 },
  "background_worker": { "status": "active", "queue_depth": 0 },
  "memory_usage_mb": 142.6,
  "uptime_seconds": 86420
}
```

---

## 2. Structured Logging & OpenTelemetry

- **Log Format:** Alberto logs in JSON or structured ANSI format using `loguru` and standard library `logging`.
- **OpenTelemetry Tracing:** Distributed trace spans are exported via OpenTelemetry OTLP (`opentelemetry-sdk>=1.45.1`) to standard collectors (Jaeger, Grafana Tempo) when `OTEL_EXPORTER_OTLP_ENDPOINT` is configured.
- **Audit Logs:** Security-relevant events (authentication, secret accesses, destructive tool calls) are stored in the `audit_logs` table and accessible under **Observability &rarr; Traces**.

---

## 3. Routine Upgrades & Migrations

To upgrade an existing Alberto deployment:

1. Pull the latest image or code:
   ```bash
   git pull origin main
   ```
2. Rebuild or restart the container:
   ```bash
   docker compose down
   docker compose up -d --build
   ```
3. The container's entrypoint runs Alembic database migrations automatically against `/data/db/alberto.db`.
4. Verify upgrade success by checking container logs:
   ```bash
   docker compose logs -f alberto | grep "migration"
   ```

---

## 4. Database Maintenance & Vacuuming

Over months of heavy use, SQLite files benefit from periodic vacuuming to reclaim deleted page space and optimize B-tree indexes:

```bash
# Clean up old deleted records
sqlite3 /data/db/alberto.db "VACUUM;"
sqlite3 /data/db/checkpoints.sqlite "VACUUM;"

# Recompute query planner statistics
sqlite3 /data/db/alberto.db "ANALYZE;"
```

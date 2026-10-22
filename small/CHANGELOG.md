# Changelog

## v0.1.0 — 2026-10-22

First release of the `small` stack: a self-hosted observability stack in one `docker compose up`.

### Included
- **Metrics**: Prometheus (scrape + rules) with `remote_write` to VictoriaMetrics (12 months), node-exporter, cAdvisor, blackbox-exporter, pushgateway, `discoverer` for automatic app `/metrics` targets.
- **Logs**: Vector reads Docker container logs and nginx file logs, parses levels, masks secrets and ships to VictoriaLogs (90 days / 20 GiB). vmalert runs LogsQL alert rules.
- **Traces**: apps send OTLP to Vector (`4317` gRPC, `4318` HTTP), forwarded to Tempo with span metrics back to Prometheus.
- **Alerting**: Prometheus and vmalert fire into Alertmanager, delivered to Telegram (critical loud, warnings silent), plus a Grafana dead man's switch.
- **Dashboards**: generated and hand-written Grafana dashboards with shared navigation and deploy/restart annotations; `scripts/check-dashboards.py` finds empty or broken panels.
- **Optional profiles**: PostgreSQL, MySQL, Redis, MongoDB, nginx, smartctl + Scrutiny exporters, and demo workloads (`demo`, `queue`, `proxy`, `search`, `nosql`, `cron`).

### Changed before release
- Vector is the only collector for logs, traces and OTLP; Grafana Alloy is no longer used.
- Continuous profiling (Alloy pprof scraping, Pyroscope, Profiles dashboard, trace-to-profile link) removed.
- Architecture diagram updated to match.

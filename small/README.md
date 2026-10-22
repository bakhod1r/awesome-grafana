# awesome-grafana

Self-hosted observability stack in one `docker compose up`: metrics, logs, traces, alerting to Telegram and ready-made Grafana dashboards.

![Architecture](docs/architecture.svg)

## What's inside

| Layer | Services |
|-------|----------|
| Metrics collection | Prometheus, node-exporter, cAdvisor, blackbox-exporter, pushgateway, speedtest-exporter, discoverer (auto-finds app `/metrics`) |
| Logs, traces | Vector (Docker logs, file logs, OTLP), nginx-demo, telemetrygen (demo profile) |
| Storage | VictoriaMetrics (metrics, 12 months), VictoriaLogs (logs, 90 days / 20 GiB), Tempo (traces + span metrics) |
| Alerting | Prometheus rules + vmalert (LogsQL rules) → Alertmanager → Telegram; Grafana dead man's switch |
| UI | Grafana (provisioned datasources and dashboards), grafana-proxy (themed nginx front) |
| Optional exporters | PostgreSQL, MySQL, Redis (each with a demo database + load generator and its own dashboard), MongoDB, nginx, smartctl + Scrutiny (enabled via profiles) |
| Demos per container type | RabbitMQ, Traefik, Elasticsearch, MongoDB + Memcached, cron jobs (profiles `queue`, `proxy`, `search`, `nosql`, `cron`) |

## How data flows

1. **Metrics** — Prometheus scrapes exporters and apps (static jobs + `discoverer` file_sd targets), evaluates recording/alert rules, and `remote_write`s everything to VictoriaMetrics. Grafana reads metrics from VictoriaMetrics.
2. **Logs** — Vector reads container stdout through the Docker socket and nginx file logs, parses levels, masks secrets, turns lines into metrics (`vector_*` on `:9598`) and ships them to VictoriaLogs. vmalert runs LogsQL alert rules against VictoriaLogs.
3. **Traces** — apps send OTLP to Vector (`vector:4317` gRPC, `vector:4318` HTTP inside Docker; `34317` / `34318` on the host), Vector forwards traces to Tempo, metrics to Prometheus, logs to VictoriaLogs. No CORS: browser SDKs need a reverse proxy in front. Tempo's metrics generator writes span metrics (with exemplars) back to Prometheus.
4. **Alerts** — Prometheus and vmalert fire into Alertmanager, which sends Telegram messages (critical loud, warnings silent). Grafana runs a dead man's switch so a dead alert pipeline is noticed too.

## Quick start

```bash
cp .env.example .env        # set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID (required)
docker compose up -d
```

Optional parts:

```bash
docker compose --profile demo up -d                         # demo traces
docker compose --profile postgres --profile mysql --profile redis up -d   # databases: exporter + demo DB + load
docker compose --profile queue --profile proxy up -d   # demo RabbitMQ (+ load) and Traefik for the Queue / Proxy dashboards
docker compose --profile search --profile nosql --profile cron up -d   # demo Elasticsearch, MongoDB + Memcached, cron jobs
```

PostgreSQL, MySQL and Redis targets are on in `prometheus/exporters/<name>.yml` (set the file to `[]` when the profile is off, or `TargetDown` fires). Other exporters: add the target there after enabling the profile.

## Settings (.env)

| Variable | What it does |
|----------|--------------|
| `TELEGRAM_BOT_TOKEN` | Bot that sends alerts (from @BotFather). Required. |
| `TELEGRAM_CHAT_ID` | Chat for critical alerts (sent with sound). Groups and channels start with `-100`; check with `https://api.telegram.org/bot<TOKEN>/getChat?chat_id=<id>`. The bot must be a member (admin in a channel). Required. |
| `TELEGRAM_WARNING_CHAT_ID` | Chat for warnings (sent silently). Empty = same as `TELEGRAM_CHAT_ID`. |
| `TELEGRAM_TOPIC_ID`, `TELEGRAM_WARNING_TOPIC_ID` | Forum topic inside the group. Empty = General. |
| `GRAFANA_URL`, `PROMETHEUS_URL`, `ALERTMANAGER_URL` | Public addresses used only for links in Telegram messages (Dashboard, Logs, Query). On a server, put its IP or domain here, not `localhost`, or the links will not open from a phone. |
| `GRAFANA_HOST` | IP Grafana binds to: `0.0.0.0` every interface, `127.0.0.1` this machine only. |
| `GRAFANA_PORT`, `GRAFANA_DIRECT_PORT` | Main UI (themed proxy, default `3000`) and plain Grafana (default `3002`). Keep `GRAFANA_URL` in sync. |
| `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD` | Grafana login. Change the password before exposing it. |
| `POSTGRES_EXPORTER_DSN` | PostgreSQL to watch (profile `postgres`). Commented out = the demo database. |
| `MYSQL_EXPORTER_ADDRESS`, `_USER`, `_PASSWORD` | MySQL to watch (profile `mysql`). Not needed without MySQL. |
| `REDIS_EXPORTER_ADDR`, `REDIS_EXPORTER_PASSWORD` | Redis to watch (profile `redis`). Default = the demo cache. |

Exporter settings are read only when their profile is started; plain `docker compose up -d` ignores them.

## Watching databases that run in Docker

A database in a container is watched like any other: the exporter only needs a network path to it.
Container health (CPU, memory, restarts) and logs need nothing at all, cAdvisor and Vector pick them up.

**Through the published port** (simplest, stack and database on the same server). The app's compose
publishes the port (for example `5433:5432`), and the exporter connects to the host:

```
POSTGRES_EXPORTER_DSN=postgresql://monitor:secret@host.docker.internal:5433/appdb?sslmode=disable
REDIS_EXPORTER_ADDR=redis://host.docker.internal:6379
```

On Linux `host.docker.internal` does not exist by default: use the server IP, or add
`extra_hosts: ["host.docker.internal:host-gateway"]` to the exporter service.

**Through the app's Docker network** (no published port, for example a database bound to `127.0.0.1`).
Attach the exporter to the app's network and use the container name:

```yaml
# docker-compose.yml (this stack)
services:
  postgres-exporter:
    networks: [default, app]
networks:
  app:
    external: true
    name: myapp_backend   # docker network ls
```

```
POSTGRES_EXPORTER_DSN=postgresql://monitor:secret@postgres:5432/appdb?sslmode=disable
```

**On another server**: open the database port to the monitoring server only (firewall), or run the
exporter on that server and add its address to `prometheus/exporters/<name>.yml`.

Use a read-only user for the exporter. PostgreSQL:

```sql
CREATE USER monitor WITH PASSWORD 'secret';
GRANT pg_monitor TO monitor;
```

## How to use it

### 1. Start the stack

1. Create a Telegram bot with [@BotFather](https://t.me/BotFather) (`/newbot`), send it a message, then open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `"chat":{"id":...}`.
2. `cp .env.example .env` and fill in `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` and a strong `GRAFANA_ADMIN_PASSWORD`.
3. `docker compose up -d` (add the `--profile ...` lines above for the demos you want).
4. Open http://localhost:33000 and log in as `admin` with the password from `.env`.
5. Check that alerts reach you: a "Watchdog" alert is always firing on purpose; in Alertmanager
   (http://localhost:39093) you should see it, and failures to deliver show on **Self Monitoring**.

### 2. Connect your own app

Run your app with Docker on the same host (any compose project, or plain `docker run`). Then:

| You want | Do this |
|----------|---------|
| CPU, memory, restarts, network | nothing — cAdvisor sees every container |
| Logs | nothing — Vector reads every container's stdout/stderr. JSON logs with `level`, `msg`, `duration_ms`, `path`, `status` give more panels |
| Metrics | serve Prometheus metrics on `/metrics` — the discoverer finds them within ~30s (labels `prometheus.port` / `prometheus.path` if they are elsewhere) |
| The right dashboard | add `container.type` (and `container.lang`, `team`, `env`) labels — see [Container labels](#container-labels-the-right-dashboard-per-container) |
| Traces | send OTLP to `http://vector:4318` (HTTP) or `vector:4317` (gRPC); set `OTEL_SERVICE_NAME` |
| Uptime and SSL checks | add the URL to `prometheus/sites.yml` (re-read every 30s) |
| Deploy markers on graphs | call `scripts/annotate-deploy.sh <service> <version>` from CI |
| Cron / batch jobs | push `cron_job_*` metrics to the Pushgateway at the end of each run (see the **Cron** dashboard description) |

Example compose service:

```yaml
services:
  api:
    image: my-api:1.4.2
    labels:
      container.type: backend
      container.lang: go
      container.team: payments
      container.env: prod
    environment:
      OTEL_EXPORTER_OTLP_ENDPOINT: http://vector:4318   # only if the app sends traces
      OTEL_SERVICE_NAME: my-api
```

### 3. Find things in Grafana

- **Home** (Server Overview): the host — CPU, memory, disks, network, internet speed, sites, Docker totals.
- **Docker** (Docker projects): every compose project with its resource use. Click a project →
  **Project** dashboard: summary plus a table of its containers. Click a container → the dashboard for its
  `container.type` (backend → App Endpoints, db → PostgreSQL, ...; unlabelled → **Container**).
  Click its *lang* cell → the runtime dashboard for that language.
- **Logs**: search every container's logs; **Traces**: slow and failed requests.
- **Alerts**: what is firing now and its history; **SLO** / **App SLO**: availability and error budgets.
- **Stack** (Self Monitoring): is the monitoring itself healthy (scrapes, storage, alert delivery).

The links in the top bar go to the same dashboards from everywhere and keep the selected time range.

### 4. Alerts

Rules live in `prometheus/rules/alerts.yml` (metrics) and `vmalert/` (log patterns). Critical alerts come to
Telegram with sound, warnings silently; each message links to the query, the dashboard and the logs, and has
a one-click Silence. Containers labelled `container.team` / `container.env` show them in the message.
Targets with `env: demo` (the demo databases, queue, proxy) are routed nowhere, so demos never page you.

### 5. Change or add dashboards

Dashboards are generated from Python in `grafana/generators/` (shared helpers in `lib.py`):

```bash
python3 grafana/generators/build.py      # rebuild all dashboards (Grafana reloads them within seconds)
python3 scripts/check-dashboards.py      # every panel query against the live stack: errors and "No data"
```

Edits made in the Grafana UI are not saved to the files: export the JSON or change the generator.

### 6. Day-to-day

```bash
docker compose ps                         # what runs
docker compose logs -f alertmanager       # why a Telegram message did not arrive
docker compose pull && docker compose up -d   # after bumping an image tag
docker compose down                       # stop; data stays in the named volumes
docker compose down -v                    # stop and DELETE all stored metrics, logs and dashboards state
```

Data lives in Docker volumes (`vm-data`, `vlogs-data`, `grafana-data`, `tempo-data`, ...). Back them up if the
history matters to you.

## Dashboards, SLOs and alerts worth knowing

| What | Where |
|------|-------|
| App SLO — availability 99.5% (non-5xx) and latency 99% within 1s per service, error budget, multi-window burn-rate alerts `AppErrorBudget*` / `AppLatencyBudget*` | dashboard **App SLO**, `prometheus/rules/{recording,alerts}.yml` |
| Probe SLO — 99.9% of blackbox probes, certificate expiry (`SslExpiresSoon` at 14 days, `SslExpiresCritical` at 3) | dashboard **Probes & SLO** |
| Disk forecast — `DiskWillFillIn24h` / `DiskWillFillIn4h` (`predict_linear`), hours-until-full panel | dashboard **Node Overview** |
| MySQL, Redis, PostgreSQL | dashboards **MySQL**, **Redis**, **PostgreSQL** |
| One project, one container | **Docker projects → Project → Container** (or the type dashboard: App Endpoints, Frontend, Queue, Worker, Proxy, Search, NoSQL, Storage, Cron) |
| Language runtime (Go, Java, Node, Python, PHP, .NET, Rust, Ruby) | dashboards **Runtime: <language>** |

Every dashboard marks events on its graphs: container (re)starts, a container running a new image (deploy or rollback), and deploys you post yourself:

```bash
scripts/annotate-deploy.sh my-api "v1.4.2"    # from CI after a deploy; GRAFANA_TOKEN for a remote Grafana
```

## Checking the dashboards

```bash
python3 grafana/generators/build.py    # rebuild generated dashboards, sync shared annotations + navigation
python3 scripts/check-dashboards.py    # run every panel query through Grafana, list errors and "No data"
```

The check exits non-zero on a query error or an unexpected empty panel, so it can run in CI against a live stack. Panels that are allowed to be empty (no SMART disks, not a replica) carry a "No value" text and are reported as `EMPTY-OK`.

## Endpoints

| URL | What |
|-----|------|
| http://localhost:33000 | Grafana (themed, via grafana-proxy) |
| http://localhost:33002 | Grafana (plain) |
| http://localhost:39090 | Prometheus |
| http://localhost:38428/vmui | VictoriaMetrics UI |
| http://localhost:39428/select/vmui | VictoriaLogs UI |
| http://localhost:39093 | Alertmanager |
| http://localhost:38880 | vmalert |
| http://localhost:33200 | Tempo API |
| http://localhost:38686/health | Vector health |
| http://localhost:38080 | cAdvisor |
| http://localhost:38081 | Scrutiny |

Grafana login: `admin` and `GRAFANA_ADMIN_PASSWORD` from `.env` (default `admin` — change it before exposing Grafana).

## Auto-discovery of your apps

`discoverer` watches the Docker host, joins Prometheus and blackbox to each project's network and adds every container that answers on `/metrics` to the `apps` job — no config edits. Override per container with labels:

| Label | Effect |
|-------|--------|
| `prometheus.scrape: "false"` | skip container |
| `prometheus.port: "1234"` | metrics port |
| `prometheus.path: "/stats"` | metrics path |
| `prometheus.service: "name"` | `service` label |

## Apps without /metrics: Beyla (no code change)

When an app has no `/metrics` and its code must not change, Grafana Beyla measures its HTTP traffic
through eBPF: requests/s, errors and latency per route, plus traces. Any language, also apps on
`--network host`. Linux only, kernel 5.8+ (`uname -r`).

1. List the apps in [beyla/beyla.yml](beyla/beyla.yml): the port each listens on and its name.
2. `docker compose --profile beyla up -d beyla`, then switch the target on in [prometheus/exporters/beyla.yml](prometheus/exporters/beyla.yml)

Prometheus scrapes it (job `beyla`) and renames the metrics to `http_requests_total` /
`http_request_duration_seconds` with `service`, `route`, `method`, `status`, so **App Endpoints** and
**App SLO** show these apps like any other. Traces go to Vector, then Tempo.

## Container labels: the right dashboard per container

Tell the stack what a container is, and Grafana opens the matching dashboard for it. Add labels in
your compose file; nothing to configure here (cAdvisor and Vector pick them up).

```yaml
services:
  api:
    labels:
      container.type: backend   # which dashboard opens
      container.lang: go        # which runtime dashboard opens
      container.team: payments  # filter + shown in Telegram alerts
      container.env: prod       # filter + shown in Telegram alerts
      container.project: shop   # optional: group under this project (default: the compose project)
```

`container.project` puts containers from `docker run` or from other compose files into one project:
`docker run --label container.project=shop --label container.type=frontend ...`

| `container.type` | Opens |
|------------------|-------|
| `backend`, `service`, `api` | **App Endpoints**: per endpoint 2xx/3xx/4xx/5xx and p50/p95/p99, status codes, Apdex, week-over-week, top errors |
| `frontend` | **Frontend**: requests, 4xx/5xx, latency, top pages and 404s, humans vs bots, referrers, broken assets, 499s (nginx-style access logs) |
| `db` | **PostgreSQL** or **MySQL**, picked from the image |
| `cache` | **Redis** |
| `storage` | **Storage** (MinIO): capacity and forecast, S3 requests, errors, latency |
| `queue` | **Queue**: backlog, in vs out, consumers, dead-lettered (RabbitMQ; Kafka and NATS sections) |
| `worker` | **Worker**: jobs done/failed, backlog, retries, job time (asynq, Celery, Sidekiq, BullMQ) + log-based view |
| `proxy` | **Proxy**: traffic per upstream, 502/503/504, latency (Traefik; Caddy, HAProxy, nginx sections) |
| `search` | **Search**: Elasticsearch / OpenSearch health, shards, search and indexing speed, JVM heap, disk watermarks |
| `nosql` | **NoSQL**: MongoDB operations, latency, scanned vs returned, cache; Memcached hit ratio, memory, evictions |
| `cron` | **Cron**: last run, last success, duration, exit code per job (jobs push `cron_job_*` to the Pushgateway) |
| `monitoring` | **Self Monitoring** (the stack's own services) |
| anything else (`mail`, `exporter`, `loadgen`, ...) | **Container**: status, restarts, CPU, memory vs limit, network, disk, logs |

Every type dashboard starts with the same *Container health* row (running, restarts, OOM kills, CPU, memory vs limit), and alerts exist per type: queue backlog / no consumers / broker alarms, Kafka lag, failing jobs, proxy upstream errors.

| `container.lang` | Runtime dashboard |
|------------------|-------------------|
| `go` | goroutines, heap, GC pauses, allocation rate |
| `java` | JVM heap, GC time, threads, classes, HikariCP pool (Micrometer or JMX exporter) |
| `node` | event loop lag, heap, GC, active handles (prom-client) |
| `python` | GC by generation, uncollectable objects, memory (prometheus_client) |
| `php` | PHP-FPM workers, listen queue (php-fpm_exporter) |
| `dotnet` | managed memory, GC, thread pool, exceptions (prometheus-net) |
| `rust`, `ruby` | process CPU, memory, file descriptors (+ Ruby GC when exported) |
| `javascript` | static SPA served by nginx (no runtime): container CPU, memory, network, restarts; requests, 4xx/5xx, latency from access logs; logs |

Where to click: **Docker projects → a project** (Project dashboard) **→ a container**, or **Docker projects → Containers by type**. The *Opens* column opens the type's dashboard,
the *lang* column the runtime one. Type, Language, Team and Env are also filters on that dashboard and
fields on every log line (`type:backend`, `team:payments`).

Databases and caches need an exporter next to them (postgres-exporter, redis_exporter); MinIO needs
`MINIO_PROMETHEUS_AUTH_TYPE=public` and the labels `prometheus.port: "9000"`,
`prometheus.path: /minio/v2/metrics/cluster`. The discoverer finds them on its own.

## Repository layout

```
alertmanager/     routing + Telegram template
vector/           log and OTLP pipeline
blackbox/         probe modules
discoverer/       app metrics auto-discovery
grafana/          provisioning, dashboards, dashboard generators
grafana-proxy/    nginx + theme.css
prometheus/       scrape config, exporters, probes, rules
tempo/            trace storage config
vmalert/          log alert rules
postgres/         demo database + load generator
mysql/            demo database + load generator
redis/            demo cache load generator
scripts/          check-dashboards.py, annotate-deploy.sh
nginx-demo/       demo nginx with file logs
traefik/          demo Traefik routes (profile "proxy")
```

## License

See [LICENSE](LICENSE).

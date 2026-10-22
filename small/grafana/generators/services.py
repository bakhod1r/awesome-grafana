"""Services: catalog of the optional services (PostgreSQL, MySQL, Redis, nginx, Traefik, MongoDB) built on the
svc:* golden-signal recording rules (prometheus/rules/recording.yml). One identical row is repeated per running
service, so a disabled exporter shows nothing at all instead of empty "No data" panels."""
from lib import *

UID, SLUG = "services", "services"
S = 'svc=~"$svc"'
ALERT_PREFIX = {"postgres": "Postgres", "mysql": "Mysql", "redis": "Redis", "nginx": "Nginx", "traefik": "Traefik", "mongodb": "Mongo"}
ALERTS_BY_SVC = " or ".join(
    f'label_replace(count(ALERTS{{alertstate="firing", alertname=~"{p}.*"}}), "svc", "{s}", "", "")' for s, p in ALERT_PREFIX.items())
ALERT_RE = "|".join(f"{p}.*" for p in ALERT_PREFIX.values())
EMPTY = "No service enabled. Enable one: docker compose --profile postgres up -d (same for mysql, redis, nginx, mongodb), then prometheus/exporters/<name>.yml"
P_CAT, P_BATCH, P_TARGETS, P_ALERTS = 901, 902, 903, 904


def novalue(p, txt):
    p["fieldConfig"]["defaults"]["noValue"] = txt
    return p


SVC_LINKS = [{"title": "Only this service", "url": f"/d/{UID}/{SLUG}?${{__url_time_range}}&var-svc=${{__data.fields.svc}}"},
             {"title": "Logs of this service", "url": "/d/logs/logs?${__url_time_range}&var-service=${__data.fields.svc}"},
             {"title": "Detailed dashboard (by tag)", "url": "/dashboards?tag=${__data.fields.svc}"}]

d = Dash(UID, "Services",
         "Catalog of optional services (PostgreSQL, MySQL, Redis, nginx, Traefik, MongoDB), each with the same golden signals: "
         "status, throughput, errors, saturation, latency. Only enabled services are shown. Below: batch jobs and scrape targets.",
         ["services", "catalog", "golden-signals", "postgres", "mysql", "redis", "nginx", "traefik", "mongodb", "pushgateway"],
         variables=[query_var("svc", "Service", "label_values(svc:up, svc)", desc="Enabled services (from the svc:up recording rule). Clicking a name in the catalog filters too.")])

d.row("Catalog — what runs and is it healthy")
d.add(text("Every service is measured with the same 5 signals (Google SRE **golden signals**): **Status**, **Throughput** (work per second), "
           "**Errors** (error share), **Saturation** (how full the main limit is), **Latency** (p95 or average). "
           "Click a service name to keep only its rows below. A newly enabled exporter gets its row automatically."), 24, 2)
d.add(novalue(stat("Services monitored", "count(svc:up)", color_mode="value", th=steps(base="blue"), graph=False,
                   desc="Services with an enabled exporter."), "0 — no service enabled"), 4, 4)
d.add(stat("Down", "count(svc:up == 0) or vector(0)", th=steps((1, "red")), graph=False, link=view(UID, SLUG, P_CAT, "Which one?"),
           desc="The exporter runs but cannot reach the service."), 4, 4)
d.add(stat("Firing alerts", f'count(ALERTS{{alertstate="firing", alertname=~"{ALERT_RE}"}}) or vector(0)', th=steps((1, "red")), graph=False,
           link=goto("alerts", "alerts", "Alerts dashboard", "&var-alertname=All"), desc="Service alerts (Postgres*, Mysql*, Redis*, Nginx*, Traefik*, Mongo*)."), 4, 4)
d.add(stat("Saturated (> 80%)", "count(svc:saturation:ratio > 0.8) or vector(0)", th=steps((1, "orange")), graph=False,
           link=view(UID, SLUG, P_CAT, "Which one?"), desc="Services above 80% of their main limit (connections or memory)."), 4, 4)
d.add(stat("Batch jobs stale / failed", "count((time() - max by (job) (push_time_seconds)) > 90000) + count(max by (job) (push_failure_time_seconds) > max by (job) (push_time_seconds)) or vector(0)",
           th=steps((1, "red")), graph=False, link=view(UID, SLUG, P_BATCH, "Batch jobs"),
           desc="Jobs that have not pushed for 25 hours or whose last push failed."), 4, 4)
d.add(stat("Scrape targets down", 'count(up == 0) or vector(0)', th=steps((1, "red")), graph=False,
           link=view(UID, SLUG, P_TARGETS, "Targets"), desc="Targets Prometheus cannot scrape (whole stack)."), 4, 4)

cat = table("Service catalog", [
    tgt(f"max by (svc) (svc:up{{{S}}})", instant=True, fmt="table"),
    tgt(f"max by (svc) (svc:throughput:rate5m{{{S}}})", instant=True, fmt="table"),
    tgt(f"max by (svc) (svc:errors:rate5m{{{S}}}) / (max by (svc) (svc:throughput:rate5m{{{S}}}) > 0)", instant=True, fmt="table"),
    tgt(f"max by (svc) (svc:saturation:ratio{{{S}}})", instant=True, fmt="table"),
    tgt(f"max by (svc) (svc:latency:seconds{{{S}}})", instant=True, fmt="table"),
    tgt(f"max by (svc) (svc:throughput:rate5m{{{S}}}) / max by (svc) (svc:throughput:rate5m{{{S}}} offset 1w) - 1", instant=True, fmt="table"),
    tgt(f"({ALERTS_BY_SVC}) and on (svc) svc:up", instant=True, fmt="table"),
], desc="One row per service. Click a name: filter, logs or the detailed dashboard (e.g. PostgreSQL). "
        "Error % = errors / throughput. vs last week = throughput compared with the same time last week.",
    sort=("svc", False),
    rename={"svc": "Service", "Value #A": "Status", "Value #B": "Throughput", "Value #C": "Error %", "Value #D": "Saturation",
            "Value #E": "Latency", "Value #F": "vs last week", "Value #G": "Alerts"},
    order=["Service", "Status", "Throughput", "Error %", "Saturation", "Latency", "vs last week", "Alerts"],
    overrides=[col("Service", width=160, links=[{**l, "url": l["url"].replace("__data.fields.svc", "__data.fields.Service")} for l in SVC_LINKS]),
               col("Status", cell=BG, mappings=vmap({"1": ("UP", "green"), "0": ("DOWN", "red")}), width=90),
               col("Throughput", unit="ops", decimals=1),
               col("Error %", unit="percentunit", cell=BG, th=steps((0.01, "yellow"), (0.05, "red")), decimals=2),
               col("Saturation", unit="percentunit", cell=GAUGE, th=steps((0.7, "yellow"), (0.85, "red")), minv=0, maxv=1),
               col("Latency", unit="s", cell=BG, th=steps((0.1, "yellow"), (0.5, "red"))),
               col("vs last week", unit="percentunit", cell=TXT, th=steps((-0.3, "green"), (0.5, "orange"), base="orange"), decimals=0),
               col("Alerts", cell=BG, th=steps((1, "red")), decimals=0)])
cat["id"] = P_CAT
novalue(cat, "-")  # empty cells; an empty catalog is explained by the stats above
d.add(cat, 24, 7)

# One row per service, repeated by $svc: same panels, same order, same colours for every service.
d.row("$svc")
d.cur["repeat"] = "svc"
F = '{svc="$svc"}'
d.add(stat("Status", f"max(svc:up{F})", th=steps((1, "green"), base="red"), mappings=vmap({"1": ("UP", "green"), "0": ("DOWN", "red")}), graph=False,
           desc="1 = the exporter reaches the service."), 4, 4)
d.add(stat("Throughput", f"max(svc:throughput:rate5m{F})", unit="ops", color_mode="value", th=steps(base="blue"), decimals=1, instant=False,
           desc="Work per second: postgres = transactions, mysql = queries, redis = commands, nginx/traefik = requests, mongodb = operations."), 4, 4)
d.add(novalue(stat("Error %", f"max(svc:errors:rate5m{F}) / (max(svc:throughput:rate5m{F}) > 0)", unit="percentunit",
                   th=steps((0.01, "yellow"), (0.05, "red")), decimals=2, instant=False,
                   desc="postgres: rollback+deadlock, mysql: aborted connects, redis: rejected+evicted, traefik: 5xx, mongodb: asserts."), "n/a"), 4, 4)
d.add(novalue(stat("Saturation", f"max(svc:saturation:ratio{F})", unit="percentunit", th=steps((0.7, "yellow"), (0.85, "red")), decimals=1, instant=False,
                   desc="How full the main limit is: connections / max, or memory / maxmemory."), "n/a"), 4, 4)
d.add(novalue(stat("Latency", f"max(svc:latency:seconds{F})", unit="s", th=steps((0.1, "yellow"), (0.5, "red")), instant=False,
                   desc="postgres/traefik: p95, redis: average command time, mysql: estimate (slow query share × long_query_time)."), "n/a"), 4, 4)
d.add(text("**$svc** · [Logs](/d/logs/logs?var-service=$svc&${__url_time_range}) · "
           "[Detailed dashboard](/dashboards?tag=$svc) · [Alerts](/d/alerts/alerts?${__url_time_range})\n\n"
           "Signal definitions: `prometheus/rules/recording.yml` → `service-signals`."), 4, 4)
d.add(compare_week("Throughput (now vs 1 week ago)", f"max(svc:throughput:rate5m{F})", "$svc", unit="ops",
                   desc="Grey line = same time last week. A big gap = traffic anomaly."), 6, 7)
d.add(ts("Error %", [tgt(f"max(svc:errors:rate5m{F}) / (max(svc:throughput:rate5m{F}) > 0)", "$svc")], unit="percentunit",
         th=steps((0.01, "yellow"), (0.05, "red")), fill=0, legend="hidden"), 6, 7)
d.add(ts("Saturation", [tgt(f"max(svc:saturation:ratio{F})", "$svc")], unit="percentunit", th=steps((0.7, "yellow"), (0.85, "red")),
         minv=0, maxv=1, legend="hidden", desc="Approaching 85% = time to raise the limit or reduce load."), 6, 7)
d.add(ts("Latency", [tgt(f"max(svc:latency:seconds{F})", "$svc")], unit="s", th=steps((0.1, "yellow"), (0.5, "red")), fill=0, legend="hidden"), 6, 7)

d.row("Batch jobs (pushgateway)")
d.add(text("Short jobs (cron, backups, migrations) push their result to the pushgateway when they finish. Example (end of a backup script):\n"
           "```\necho \"batch_last_success_timestamp_seconds $(date +%s)\" | curl --data-binary @- http://localhost:9091/metrics/job/backup\n```\n"
           "Red **Since last push** = the job has not run for 25 hours. **Status** failed = the last push reported a failure."), 24, 3)
batch = table("Batch jobs", [
    tgt("time() - max by (job) (push_time_seconds)", instant=True, fmt="table"),
    tgt("time() - max by (job) (batch_last_success_timestamp_seconds)", instant=True, fmt="table"),
    tgt("max by (job) (push_failure_time_seconds) > bool max by (job) (push_time_seconds)", instant=True, fmt="table"),
], desc="Each job: time since last push, time since last success, status.",
    sort=("Since last push", True),
    rename={"Value #A": "Since last push", "Value #B": "Since last success", "Value #C": "Status"},
    order=["job", "Status", "Since last push", "Since last success"],
    overrides=[col("Since last push", unit="s", cell=BG, th=steps((90000, "red")), decimals=0),
               col("Since last success", unit="s", cell=BG, th=steps((90000, "red")), decimals=0),
               col("Status", cell=BG, mappings=vmap({"0": ("ok", "green"), "1": ("failed", "red")}))])
batch["id"] = P_BATCH
novalue(batch, "No job has pushed yet — run the example above")
d.add(batch, 12, 8)
d.add(novalue(state_timeline("Pushes over time", [tgt("count by (job) (changes(push_time_seconds[5m]) > 0)", "{{job}}")],
                             desc="Each coloured block = the job pushed at that time.", mappings=vmap({"1": ("push", "green")})), "No pushes"), 12, 8)

d.row("Scrape targets — butun stack", collapsed=True)
tg = table("Targets", [
    tgt('max by (job, instance) (up)', instant=True, fmt="table"),
    tgt('max by (job, instance) (scrape_duration_seconds)', instant=True, fmt="table"),
    tgt('max by (job, instance) (scrape_samples_scraped)', instant=True, fmt="table"),
    tgt('max by (job, instance) (scrape_series_added)', instant=True, fmt="table"),
], desc="Everything Prometheus scrapes. High duration = slow exporter. Samples = cardinality (more = costlier).",
    sort=("Up", True),
    rename={"Value #A": "Up", "Value #B": "Scrape time", "Value #C": "Samples", "Value #D": "New series"},
    order=["job", "instance", "Up"],
    overrides=[col("instance", width=260), col("Up", cell=BG, mappings=vmap({"1": ("UP", "green"), "0": ("DOWN", "red")})),
               col("Scrape time", unit="s", cell=TXT, th=steps((1, "yellow"), (5, "red")), decimals=3),
               col("Samples", cell=BAR, th=steps((5000, "yellow"), (20000, "red")))])
tg["id"] = P_TARGETS
tg["fieldConfig"]["defaults"]["custom"]["filterable"] = True
d.add(tg, 24, 10)
d.add(ts("Scrape duration (top 10)", [tgt('topk(10, max by (job) (scrape_duration_seconds))', "{{job}}")], unit="s", fill=0), 12, 7)
d.add(ts("Samples per scrape by job", [tgt('sum by (job) (scrape_samples_scraped)', "{{job}}")], stack=True), 12, 7)

d.write("Apps/services.json")

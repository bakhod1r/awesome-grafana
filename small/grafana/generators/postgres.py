"""PostgreSQL: health, per-service (application_name) latency, top/slow queries, logs, tables, locks, WAL."""
import json, os, sys
from lib import nav_links, project_var, ROOT

VM = {"type": "prometheus", "uid": "victoriametrics"}
VL = {"type": "victoriametrics-logs-datasource", "uid": "victorialogs"}
I = 'instance=~"$instance"'
D = 'datname=~"$datname"'
A = 'application=~"$application"'
H = 'vector_postgres_statement_duration_seconds_bucket{pg_app=~"$application", pg_db=~"$datname"}'
LOGF = 'service:="postgres" pg_app:~"${application:regex}" pg_db:~"${datname:regex}"'

panels = []
_id = [0]
y = [0]


def nid():
    _id[0] += 1
    return _id[0]


def tgt(expr, legend="", instant=False, ref=None, fmt=None):
    t = {"refId": ref or "A", "expr": expr, "legendFormat": legend, "datasource": VM}
    if instant:
        t["instant"] = True
        t["range"] = False
    if fmt:
        t["format"] = fmt
    return t


def refs(ts):
    for i, t in enumerate(ts):
        t["refId"] = chr(65 + i)
    return ts


class Row:
    def __init__(self, title, collapsed=False):
        self.p = {"type": "row", "id": nid(), "title": title, "collapsed": collapsed,
                  "gridPos": {"x": 0, "y": y[0], "w": 24, "h": 1}, "panels": []}
        panels.append(self.p)
        y[0] += 1
        self.x = 0
        self.rowh = 0

    def add(self, p, w, h):
        if self.x + w > 24:
            y[0] += self.rowh
            self.x = 0
            self.rowh = 0
        p["id"] = p.get("id") or nid()
        p["gridPos"] = {"x": self.x, "y": y[0], "w": w, "h": h}
        self.x += w
        self.rowh = max(self.rowh, h)
        if self.p["collapsed"]:
            self.p["panels"].append(p)
        else:
            panels.append(p)
        return p

    def end(self):
        y[0] += self.rowh


def steps(*pairs, base="green"):
    s = [{"color": base, "value": None}]
    for v, c in pairs:
        s.append({"color": c, "value": v})
    return {"mode": "absolute", "steps": s}


def stat(title, expr, unit="short", th=None, desc="", decimals=None, mappings=None, link=None, color_mode="background", text_mode="value", legend=""):
    p = {"type": "stat", "title": title, "description": desc, "datasource": VM,
         "targets": [tgt(expr, legend, instant=True)],
         "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                     "colorMode": color_mode, "graphMode": "area", "textMode": text_mode, "justifyMode": "center", "wideLayout": True},
         "fieldConfig": {"defaults": {"unit": unit, "thresholds": th or steps(), "color": {"mode": "thresholds"}, "mappings": mappings or [],
                                      "links": [link] if link else []}, "overrides": []}}
    if decimals is not None:
        p["fieldConfig"]["defaults"]["decimals"] = decimals
    return p


def ts(title, targets, unit="short", desc="", stack=False, fill=10, th=None, legend_calcs=("mean", "max", "lastNotNull"), draw="line", minv=None, maxv=None, overrides=None, links=None):
    p = {"type": "timeseries", "title": title, "description": desc, "datasource": VM, "targets": refs(targets),
         "fieldConfig": {"defaults": {"unit": unit, "color": {"mode": "palette-classic-by-name"},
                                      "custom": {"drawStyle": draw, "lineWidth": 2, "fillOpacity": fill, "gradientMode": "opacity",
                                                 "showPoints": "never", "spanNulls": True,
                                                 "stacking": {"mode": "normal" if stack else "none", "group": "A"},
                                                 "thresholdsStyle": {"mode": "dashed" if th else "off"}},
                                      "thresholds": th or steps(), "links": links or []},
                         "overrides": overrides or []},
         "options": {"legend": {"displayMode": "table", "placement": "bottom", "calcs": list(legend_calcs), "showLegend": True},
                     "tooltip": {"mode": "multi", "sort": "desc"}}}
    if minv is not None:
        p["fieldConfig"]["defaults"]["min"] = minv
    if maxv is not None:
        p["fieldConfig"]["defaults"]["max"] = maxv
    return p


def table(title, targets, desc="", overrides=None, sort=None, hide=(), rename=None, order=None, unit=None):
    exclude = {k: True for k in ("Time", "__name__", "job", "instance", "server") + tuple(hide)}
    org = {"excludeByName": exclude, "renameByName": rename or {}, "indexByName": {k: i for i, k in enumerate(order or [])}}
    p = {"type": "table", "title": title, "description": desc, "datasource": VM, "targets": refs(targets),
         "transformations": [{"id": "merge", "options": {}}, {"id": "organize", "options": org}],
         "fieldConfig": {"defaults": {"custom": {"align": "auto", "cellOptions": {"type": "auto"}, "filterable": True},
                                      "thresholds": steps()}, "overrides": overrides or []},
         "options": {"showHeader": True, "cellHeight": "sm", "footer": {"show": False},
                     "sortBy": [{"displayName": sort[0], "desc": sort[1]}] if sort else []}}
    if unit:
        p["fieldConfig"]["defaults"]["unit"] = unit
    return p


def col(name, unit=None, cell=None, th=None, width=None, decimals=None, links=None, minv=None, maxv=None):
    props = []
    if unit:
        props.append({"id": "unit", "value": unit})
    if cell:
        props.append({"id": "custom.cellOptions", "value": cell})
    if th:
        props.append({"id": "thresholds", "value": th})
        props.append({"id": "color", "value": {"mode": "thresholds"}})
    if width:
        props.append({"id": "custom.width", "value": width})
    if decimals is not None:
        props.append({"id": "decimals", "value": decimals})
    if links:
        props.append({"id": "links", "value": links})
    if minv is not None:
        props.append({"id": "min", "value": minv})
    if maxv is not None:
        props.append({"id": "max", "value": maxv})
    return {"matcher": {"id": "byName", "options": name}, "properties": props}


BG = {"type": "color-background", "mode": "gradient"}
TXT = {"type": "color-text"}
GAUGE = {"type": "gauge", "mode": "lcd", "valueDisplayMode": "text"}


def logs(title, expr, desc=""):
    return {"type": "logs", "title": title, "description": desc, "datasource": VL,
            "targets": [{"refId": "A", "datasource": VL, "queryType": "instant", "expr": expr}],
            "options": {"showTime": True, "wrapLogMessage": True, "sortOrder": "Descending", "enableLogDetails": True,
                        "prettifyLogMessage": False, "dedupStrategy": "none", "showLabels": False, "showCommonLabels": False}}


def vl_ts(title, expr, legend, desc="", unit="short", stack=True):
    p = ts(title, [], unit=unit, desc=desc, stack=stack, draw="bars", fill=80, legend_calcs=("sum",))
    p["datasource"] = VL
    p["targets"] = [{"refId": "A", "datasource": VL, "queryType": "statsRange", "expr": expr, "legendFormat": legend}]
    return p


def vl_table(title, expr, desc="", overrides=None):
    return {"type": "table", "title": title, "description": desc, "datasource": VL,
            "targets": [{"refId": "A", "datasource": VL, "queryType": "stats", "expr": expr}],
            "transformations": [{"id": "organize", "options": {"excludeByName": {"Time": True}}}],
            "fieldConfig": {"defaults": {"custom": {"filterable": True, "cellOptions": {"type": "auto"}}}, "overrides": overrides or []},
            "options": {"showHeader": True, "cellHeight": "sm"}}


def view(pid, title):
    return {"title": title, "url": "/d/postgres/postgresql?${__url_time_range}&${__all_variables}&viewPanel=%d" % pid}


SVC_LINK = [{"title": "Only this service: ${__data.fields.application}",
             "url": "/d/postgres/postgresql?${__url_time_range}&var-instance=${instance}&var-datname=${datname}&var-application=${__data.fields.application}"}]
DB_LINK = [{"title": "Only this database: ${__data.fields.datname}",
            "url": "/d/postgres/postgresql?${__url_time_range}&var-instance=${instance}&var-application=${application}&var-datname=${__data.fields.datname}"}]

# Panel ids that health stats jump to (viewPanel). Fixed so links stay valid.
P_SVC_TABLE, P_TOPQ, P_SLOWLOG, P_ERRLOG, P_LOCKS, P_DB_TABLE, P_TABLES, P_LAT_APP, P_REPL, P_ALERTS = 901, 902, 903, 904, 905, 906, 907, 908, 909, 910

# ─────────────────────────────── Health ───────────────────────────────
r = Row("Health — is everything OK?")
r.add({"type": "text", "title": "", "transparent": True, "options": {"mode": "markdown", "content":
       "**How to read:** green = fine, yellow = watch, red = fix now. "
       "Click any card to open the matching detail panel full screen. "
       "Filter with `Service` / `Database` at the top, or click a service or DB name in any table. "
       "Rows below: **Services** → **Slow queries & p95** → **Logs** → Databases → Tables → Locks → Internals."}}, 24, 2)
r.add(stat("Status", f'max(pg_up{{{I}}})', th=steps((1, "green"), base="red"),
           mappings=[{"type": "value", "options": {"0": {"text": "DOWN", "color": "red"}, "1": {"text": "UP", "color": "green"}}}],
           desc="Whether postgres-exporter can connect. DOWN = database is down or the DSN is wrong."), 3, 4)
r.add(stat("Uptime", f'time() - max(pg_postmaster_start_time_seconds{{{I}}})', unit="s", th=steps((600, "green"), base="orange"),
           desc="Time since the server started. Unexpectedly short = crash or OOM kill.", decimals=0), 3, 4)
r.add(stat("Version", f'max by (short_version) (pg_static{{{I}}})', text_mode="name", color_mode="none", legend="{{short_version}}",
           desc="PostgreSQL versiyasi."), 3, 4)
r.add(stat("Connections used", f'sum(pg_stat_activity_count{{{I}}}) / max(pg_settings_max_connections{{{I}}}) * 100', unit="percent",
           th=steps((70, "yellow"), (80, "red")), decimals=0, link=view(P_SVC_TABLE, "Which service holds the connections?"),
           desc="Share of max_connections in use. At 100% new connections are refused. Alert: 80%."), 3, 4)
r.add(stat("Transactions/s", f'sum(rate(pg_stat_database_xact_commit{{{I}, {D}}}[5m]) + rate(pg_stat_database_xact_rollback{{{I}, {D}}}[5m]))',
           unit="ops", color_mode="value", th=steps(base="blue"), desc="Commits + rollbacks per second (TPS).", decimals=1), 3, 4)
r.add(stat("p95 latency", f'1000 * histogram_quantile(0.95, sum by (le) (rate({H}[5m])))', unit="ms", th=steps((100, "yellow"), (500, "red")),
           link=view(P_LAT_APP, "p95 by service"), decimals=1,
           desc="95% of statements finish faster than this (from the statement log). Alert: 500 ms."), 3, 4)
r.add(stat("Cache hit", f'sum(rate(pg_stat_database_blks_hit{{{I}, {D}}}[5m])) / (sum(rate(pg_stat_database_blks_hit{{{I}, {D}}}[5m])) + sum(rate(pg_stat_database_blks_read{{{I}, {D}}}[5m])))',
           unit="percentunit", th=steps((0.9, "yellow"), (0.99, "green"), base="red"), decimals=2,
           link=view(P_DB_TABLE, "By database"),
           desc="Share of block reads served from RAM (shared_buffers). 99%+ is normal for OLTP. Below 90% = reading from disk."), 3, 4)
r.add(stat("Firing alerts", 'count(ALERTS{alertname=~"Postgres.*", alertstate="firing"}) or vector(0)',
           th=steps((1, "red")), link=view(P_ALERTS, "Which alerts?"), desc="Postgres* alerts firing now."), 3, 4)
r.end()
r.add(stat("Blocked sessions", f'sum(pg_app_blocked_sessions{{{I}, {A}, {D}}}) or vector(0)', th=steps((1, "yellow"), (5, "red")),
           link=view(P_LOCKS, "Who blocks whom?"), desc="Sessions waiting on another session's lock."), 3, 4)
r.add(stat("Longest transaction", f'max(pg_app_activity_max_tx_seconds{{{I}, {A}, {D}}})', unit="s",
           th=steps((60, "yellow"), (300, "red")), link=view(P_SVC_TABLE, "Which service?"), decimals=0,
           desc="Oldest open transaction. Long transactions hold locks and block VACUUM. Alert: 5 min."), 3, 4)
r.add(stat("Idle in transaction", f'sum(pg_app_activity_count{{{I}, {A}, {D}, state=~"idle in transaction.*"}}) or vector(0)',
           th=steps((1, "yellow"), (5, "red")), link=view(P_SVC_TABLE, "Which service?"),
           desc="Sessions that ran BEGIN and went quiet without COMMIT, usually an application bug."), 3, 4)
r.add(stat("Slow statements/min (>100ms)", f'(sum(rate({H.replace("_bucket{", "_count{")}[5m])) - sum(rate({H.replace("}", ", le=\"0.1\"}")}[5m]))) * 60',
           th=steps((1, "yellow"), (30, "red")), decimals=1, link=view(P_SLOWLOG, "Slow query log"),
           desc="Statements slower than 100 ms, per minute."), 3, 4)
r.add(stat("Errors/min", 'sum(rate(vector_log_lines_total{service="postgres", level=~"error|fatal|panic"}[5m])) * 60 or vector(0)',
           th=steps((0.5, "yellow"), (10, "red")), decimals=1, link=view(P_ERRLOG, "Error logs"),
           desc="ERROR/FATAL/PANIC lines in the PostgreSQL log, per minute."), 3, 4)
r.add(stat("Deadlocks (range)", f'sum(increase(pg_stat_database_deadlocks{{{I}, {D}}}[$__range]))', th=steps((1, "red")), decimals=0,
           link=view(P_ERRLOG, "Deadlock logs"), desc="Deadlocks in the selected range. Each one = one transaction killed."), 3, 4)
r.add(stat("Databases size", f'sum(pg_database_size_bytes{{{I}, {D}}})', unit="bytes", color_mode="value", th=steps(base="blue"),
           link=view(P_DB_TABLE, "By database"), desc="Total size of the selected databases."), 3, 4)
r.add(stat("XID wraparound", f'max(pg_database_wraparound_age_datfrozenxid_seconds{{{I}, {D}}}) / 2147483648', unit="percentunit",
           th=steps((0.25, "yellow"), (0.5, "red")), decimals=1, link=view(P_REPL, "XID age by database"),
           desc="Share of the transaction ID limit (2^31) used. At 100% the database goes read-only and needs VACUUM FREEZE."), 3, 4)
r.end()

# ─────────────────────────────── Services ───────────────────────────────
r = Row("Services — by application_name (who does what)")
svc = table("Services overview", [
    tgt(f'sum by (application) (pg_app_activity_count{{{I}, {A}, {D}}})', instant=True, fmt="table"),
    tgt(f'sum by (application) (pg_app_activity_count{{{I}, {A}, {D}, state="active"}})', instant=True, fmt="table"),
    tgt(f'sum by (application) (pg_app_activity_count{{{I}, {A}, {D}, state=~"idle in transaction.*"}})', instant=True, fmt="table"),
    tgt(f'sum by (application) (pg_app_activity_count{{{I}, {A}, {D}, wait_event_type="Lock"}})', instant=True, fmt="table"),
    tgt(f'max by (application) (pg_app_activity_max_tx_seconds{{{I}, {A}, {D}}})', instant=True, fmt="table"),
    tgt(f'label_replace(sum by (pg_app) (rate({H.replace("_bucket{", "_count{")}[5m])), "application", "$1", "pg_app", "(.*)")', instant=True, fmt="table"),
    tgt(f'label_replace(1000 * histogram_quantile(0.50, sum by (le, pg_app) (rate({H}[5m]))), "application", "$1", "pg_app", "(.*)")', instant=True, fmt="table"),
    tgt(f'label_replace(1000 * histogram_quantile(0.95, sum by (le, pg_app) (rate({H}[5m]))), "application", "$1", "pg_app", "(.*)")', instant=True, fmt="table"),
    tgt(f'label_replace(1000 * histogram_quantile(0.99, sum by (le, pg_app) (rate({H}[5m]))), "application", "$1", "pg_app", "(.*)")', instant=True, fmt="table"),
    tgt(f'label_replace(sum by (pg_app) (rate(vector_log_lines_total{{service="postgres", level=~"error|fatal|panic", pg_app=~"$application"}}[5m])) * 60, "application", "$1", "pg_app", "(.*)")', instant=True, fmt="table"),
], desc="One row per service (the app's application_name). Click a name to filter the whole dashboard to it. "
        "p50/p95/p99 = statement execution time (from the log). 'unknown' = apps that set no application_name.",
    sort=("p95", True), hide=("pg_app",),
    rename={"Value #A": "Connections", "Value #B": "Active", "Value #C": "Idle in tx", "Value #D": "Waiting on lock",
            "Value #E": "Longest tx", "Value #F": "Statements/s", "Value #G": "p50", "Value #H": "p95", "Value #I": "p99", "Value #J": "Errors/min"},
    order=["application"],
    overrides=[col("application", links=SVC_LINK, width=180),
               col("Connections", cell=GAUGE, th=steps((20, "yellow"), (50, "red")), minv=0, maxv=100),
               col("Idle in tx", cell=BG, th=steps((1, "yellow"), (3, "red"))),
               col("Waiting on lock", cell=BG, th=steps((1, "orange"), (3, "red"))),
               col("Longest tx", unit="s", cell=BG, th=steps((60, "yellow"), (300, "red")), decimals=0),
               col("Statements/s", unit="ops", decimals=1),
               col("p50", unit="ms", decimals=2),
               col("p95", unit="ms", cell=BG, th=steps((100, "yellow"), (500, "red")), decimals=2),
               col("p99", unit="ms", cell=BG, th=steps((250, "yellow"), (1000, "red")), decimals=2),
               col("Errors/min", cell=BG, th=steps((0.5, "yellow"), (5, "red")), decimals=1)])
svc["id"] = P_SVC_TABLE
r.add(svc, 24, 9)
lat = ts("p95 latency by service", [tgt(f'1000 * histogram_quantile(0.95, sum by (le, pg_app) (rate({H}[5m])))', "{{pg_app}}")], unit="ms",
         th=steps((100, "yellow"), (500, "red")), fill=0,
         desc="p95 statement time per service. When a line rises, find the heaviest query of that DB in 'Top queries'.")
lat["id"] = P_LAT_APP
r.add(lat, 12, 8)
r.add(ts("p50 / p95 / p99 (selected services)", [
    tgt(f'1000 * histogram_quantile(0.50, sum by (le) (rate({H}[5m])))', "p50"),
    tgt(f'1000 * histogram_quantile(0.95, sum by (le) (rate({H}[5m])))', "p95"),
    tgt(f'1000 * histogram_quantile(0.99, sum by (le) (rate({H}[5m])))', "p99"),
    tgt(f'1000 * histogram_quantile(0.999, sum by (le) (rate({H}[5m])))', "p99.9")], unit="ms", fill=0,
    desc="Overall percentiles for the selected services/DBs. A big p99 vs p50 gap = a few very slow queries."), 12, 8)
r.add({"type": "heatmap", "title": "Latency distribution (heatmap)", "datasource": VM,
       "description": "Each cell = statements that ran at that speed at that time. Bright spots high up = a wave of slow queries.",
       "targets": [{"refId": "A", "datasource": VM, "expr": f'sum by (le) (increase({H}[$__rate_interval]))', "format": "heatmap", "legendFormat": "{{le}}"}],
       "options": {"calculate": False, "yAxis": {"unit": "s"}, "cellGap": 1, "color": {"mode": "scheme", "scheme": "Turbo", "steps": 64, "exponent": 0.5, "scale": "exponential"},
                   "tooltip": {"mode": "single", "yHistogram": True}, "legend": {"show": True}, "rowsFrame": {"layout": "auto"}}}, 12, 8)
r.add(ts("Statements/s by service", [tgt(f'sum by (pg_app) (rate({H.replace("_bucket{", "_count{")}[5m]))', "{{pg_app}}")], unit="ops", stack=True,
         desc="Statements per second per service (from the log)."), 12, 8)
r.add(ts("Connections by service", [tgt(f'sum by (application) (pg_app_activity_count{{{I}, {A}, {D}}})', "{{application}}")], stack=True,
         desc="Connections held per service. A sudden rise = connection leak or pool misconfiguration."), 8, 8)
r.add(ts("Connections by state", [tgt(f'sum by (state) (pg_app_activity_count{{{I}, {A}, {D}}})', "{{state}}"),
                                  tgt(f'max(pg_settings_max_connections{{{I}}})', "max_connections")], stack=False,
         desc="active = running a query, idle = waiting in the pool, idle in transaction = a problem.",
         overrides=[{"matcher": {"id": "byName", "options": "max_connections"}, "properties": [
             {"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}}, {"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [10, 10]}}, {"id": "custom.fillOpacity", "value": 0}]}]), 8, 8)
r.add(ts("What sessions wait on", [tgt(f'sum by (application, wait_event_type) (pg_app_activity_count{{{I}, {A}, {D}, state="active", wait_event_type!="none"}})', "{{application}} · {{wait_event_type}}")],
         stack=True, draw="bars", fill=70,
         desc="What active sessions wait on: Lock = another transaction, IO = disk, LWLock = internal contention, Client = the app is not responding."), 8, 8)
r.add(ts("Longest transaction by service", [tgt(f'max by (application) (pg_app_activity_max_tx_seconds{{{I}, {A}, {D}}})', "{{application}}")],
         unit="s", th=steps((60, "yellow"), (300, "red")), fill=0, desc="Oldest open transaction per service."), 8, 8)
r.add(ts("Idle in transaction by service", [tgt(f'max by (application) (pg_app_activity_max_idle_tx_seconds{{{I}, {A}, {D}}})', "{{application}}")],
         unit="s", th=steps((60, "yellow"), (300, "red")), fill=0, desc="Time spent idle inside a transaction. Alert: 5 min."), 8, 8)
r.add(ts("Longest running query by service", [tgt(f'max by (application) (pg_app_activity_max_query_seconds{{{I}, {A}, {D}}})', "{{application}}")],
         unit="s", th=steps((10, "yellow"), (60, "red")), fill=0, desc="Longest currently running query, per service."), 8, 8)
r.end()

# ─────────────────────────────── Slow queries ───────────────────────────────
r = Row("Slow queries & top statements (pg_stat_statements)")
TQ = f'{{{I}, {D}}}'
topq = table("Top queries — 30 most time-consuming", [
    tgt(f'rate(pg_top_statements_exec_seconds{TQ}[$__range]) / scalar(sum(rate(pg_top_statements_exec_seconds{TQ}[$__range]))) ', instant=True, fmt="table"),
    tgt(f'rate(pg_top_statements_calls{TQ}[$__range])', instant=True, fmt="table"),
    tgt(f'pg_top_statements_mean_seconds{TQ} * 1000', instant=True, fmt="table"),
    tgt(f'pg_top_statements_max_seconds{TQ} * 1000', instant=True, fmt="table"),
    tgt(f'pg_top_statements_stddev_seconds{TQ} * 1000', instant=True, fmt="table"),
    tgt(f'rate(pg_top_statements_rows{TQ}[$__range]) / rate(pg_top_statements_calls{TQ}[$__range])', instant=True, fmt="table"),
    tgt(f'rate(pg_top_statements_shared_blks_hit{TQ}[$__range]) / (rate(pg_top_statements_shared_blks_hit{TQ}[$__range]) + rate(pg_top_statements_shared_blks_read{TQ}[$__range]))', instant=True, fmt="table"),
    tgt(f'rate(pg_top_statements_temp_blks_written{TQ}[$__range]) * 8192', instant=True, fmt="table"),
    tgt(f'rate(pg_top_statements_io_seconds{TQ}[$__range]) / rate(pg_top_statements_exec_seconds{TQ}[$__range])', instant=True, fmt="table"),
], desc="pg_stat_statements: normalised queries ($1, $2 instead of values) over the selected range. "
        "'Time share' = share of total DB time spent on the query; optimise from the top. "
        "Low cache hit or high temp = needs an index or more work_mem. Click a column to sort, use the filter icon to search.",
    sort=("Time share", True), hide=("queryid",),
    rename={"Value #A": "Time share", "Value #B": "Calls/s", "Value #C": "Mean", "Value #D": "Max", "Value #E": "Stddev",
            "Value #F": "Rows/call", "Value #G": "Cache hit", "Value #H": "Temp written/s", "Value #I": "IO share", "usename": "user", "datname": "db"},
    order=["query", "db", "user", "Time share", "Calls/s", "Mean", "Max", "Stddev", "Rows/call", "Cache hit", "Temp written/s", "IO share"],
    overrides=[col("query", width=520), col("db", width=90, links=[{"title": "Only this database", "url": "/d/postgres/postgresql?${__url_time_range}&var-instance=${instance}&var-datname=${__value.raw}"}]),
               col("user", width=90),
               col("Time share", unit="percentunit", cell={"type": "gauge", "mode": "gradient", "valueDisplayMode": "text"}, th=steps((0.2, "yellow"), (0.5, "red")), minv=0, maxv=1, decimals=1),
               col("Calls/s", unit="ops", decimals=2),
               col("Mean", unit="ms", cell=BG, th=steps((50, "yellow"), (250, "red")), decimals=2),
               col("Max", unit="ms", cell=TXT, th=steps((250, "yellow"), (1000, "red")), decimals=1),
               col("Stddev", unit="ms", decimals=2),
               col("Rows/call", decimals=1),
               col("Cache hit", unit="percentunit", cell=TXT, th=steps((0.9, "yellow"), (0.99, "green"), base="red"), decimals=1),
               col("Temp written/s", unit="Bps", cell=TXT, th=steps((1, "yellow"), (1048576, "red"))),
               col("IO share", unit="percentunit", decimals=0)])
topq["id"] = P_TOPQ
r.add(topq, 24, 12)
r.add(ts("Time spent per query (top 10)", [tgt(f'topk(10, rate(pg_top_statements_exec_seconds{TQ}[5m]))', "{{datname}} · {{query}}")], unit="s", stack=True,
         desc="Seconds per second the DB spends on the query (1 = one CPU core fully busy).", legend_calcs=("mean", "max")), 12, 9)
r.add(ts("Mean time per query (top 10 slowest)", [tgt(f'topk(10, pg_top_statements_mean_seconds{TQ} * 1000)', "{{datname}} · {{query}}")], unit="ms", fill=0,
         desc="Mean time per execution since the last reset, so it moves slowly.", legend_calcs=("lastNotNull", "max")), 12, 9)
slow = logs("Slow statement log (> 100 ms)",
            LOGF + ' "duration:" | extract "duration: <duration_ms> ms" | filter duration_ms:>100 | sort by (_time desc) | limit 500',
            desc="Every statement slower than 100 ms from the PostgreSQL log, with real parameters. Expand a line for pg_app, pg_db, duration_ms.")
slow["id"] = P_SLOWLOG
r.add(slow, 14, 11)
r.add(vl_table("Slowest statements (selected range)",
               LOGF + ' "duration:" | extract "duration: <duration_ms> ms  <kind>: <stmt>" | filter duration_ms:>100 | stats by (pg_app, pg_db, stmt) count() hits, max(duration_ms) max_ms, avg(duration_ms) avg_ms | sort by (max_ms desc) | limit 30',
               desc="Slow statements from the log grouped by text: count, slowest, average (ms).",
               overrides=[col("stmt", width=380), col("max_ms", unit="ms", cell=BG, th=steps((250, "yellow"), (1000, "red")), decimals=0),
                          col("avg_ms", unit="ms", decimals=0)]), 10, 11)
r.end()

# ─────────────────────────────── Logs ───────────────────────────────
r = Row("Logs — errors, locks, deadlocks")
r.add(vl_ts("Log lines by level", LOGF + ' | stats by (level) count()', "{{level}}",
            desc="PostgreSQL log volume by level. Red error bars = a burst of errors."), 12, 7)
r.add(vl_ts("Errors by service", LOGF + ' level:(error OR fatal OR panic) | stats by (pg_app) count()', "{{pg_app}}",
            desc="Which service produces errors."), 12, 7)
err = logs("Errors, deadlocks, lock waits, temp files",
           LOGF + ' (level:(error OR fatal OR panic OR warn) OR "deadlock" OR "still waiting for" OR "temporary file" OR "checkpoints are occurring") | sort by (_time desc) | limit 500',
           desc="Important lines: ERROR/FATAL, deadlock detected, lock waits (log_lock_waits), temp files (work_mem too small), checkpoints too frequent.")
err["id"] = P_ERRLOG
r.add(err, 14, 11)
r.add(vl_table("Top error messages", LOGF + ' level:(error OR fatal OR panic) | stats by (pg_app, _msg) count() hits | sort by (hits desc) | limit 20',
               desc="Most repeated errors.", overrides=[col("_msg", width=420), col("hits", cell=BG, th=steps((10, "yellow"), (100, "red")))]), 10, 11)
r.add(logs("All PostgreSQL logs", LOGF + ' | sort by (_time desc) | limit 1000', desc="All log lines (filtered). Full search: Logs dashboard."), 24, 10)
r.end()

# ─────────────────────────────── Databases ───────────────────────────────
r = Row("Databases", collapsed=True)
DS = f'{{{I}, {D}, datname!~"template.*"}}'
dbt = table("Databases overview", [
    tgt(f'pg_database_size_bytes{DS}', instant=True, fmt="table"),
    tgt(f'deriv(pg_database_size_bytes{DS}[6h]) * 86400', instant=True, fmt="table"),
    tgt(f'predict_linear(pg_database_size_bytes{DS}[24h], 30 * 86400)', instant=True, fmt="table"),
    tgt(f'sum by (datname) (pg_stat_database_numbackends{DS})', instant=True, fmt="table"),
    tgt(f'sum by (datname) (rate(pg_stat_database_xact_commit{DS}[5m]) + rate(pg_stat_database_xact_rollback{DS}[5m]))', instant=True, fmt="table"),
    tgt(f'sum by (datname) (rate(pg_stat_database_xact_rollback{DS}[5m])) / sum by (datname) (rate(pg_stat_database_xact_commit{DS}[5m]) + rate(pg_stat_database_xact_rollback{DS}[5m]))', instant=True, fmt="table"),
    tgt(f'sum by (datname) (rate(pg_stat_database_blks_hit{DS}[5m])) / sum by (datname) (rate(pg_stat_database_blks_hit{DS}[5m]) + rate(pg_stat_database_blks_read{DS}[5m]))', instant=True, fmt="table"),
    tgt(f'sum by (datname) (rate(pg_stat_database_temp_bytes{DS}[5m]))', instant=True, fmt="table"),
    tgt(f'sum by (datname) (increase(pg_stat_database_deadlocks{DS}[$__range]))', instant=True, fmt="table"),
    tgt(f'max by (datname) (pg_database_wraparound_age_datfrozenxid_seconds{DS})', instant=True, fmt="table"),
], desc="Each database: size, growth, 30-day forecast, load and health. Click a DB name to filter the dashboard.",
    sort=("Size", True), hide=("datid",),
    rename={"Value #A": "Size", "Value #B": "Growth/day", "Value #C": "Size in 30d", "Value #D": "Connections", "Value #E": "TPS",
            "Value #F": "Rollback %", "Value #G": "Cache hit", "Value #H": "Temp/s", "Value #I": "Deadlocks", "Value #J": "XID age"},
    order=["datname"],
    overrides=[col("datname", links=DB_LINK, width=140), col("Size", unit="bytes", cell={"type": "gauge", "mode": "basic", "valueDisplayMode": "text"}, decimals=1),
               col("Growth/day", unit="bytes", decimals=1), col("Size in 30d", unit="bytes", decimals=1),
               col("TPS", unit="ops", decimals=1), col("Rollback %", unit="percentunit", cell=TXT, th=steps((0.05, "yellow"), (0.2, "red")), decimals=1),
               col("Cache hit", unit="percentunit", cell=BG, th=steps((0.9, "yellow"), (0.99, "green"), base="red"), decimals=2),
               col("Temp/s", unit="Bps"), col("Deadlocks", cell=BG, th=steps((1, "red")), decimals=0),
               col("XID age", unit="short", cell=TXT, th=steps((500000000, "yellow"), (1000000000, "red")))])
dbt["id"] = P_DB_TABLE
r.add(dbt, 24, 8)
r.add(ts("Database size", [tgt(f'pg_database_size_bytes{DS}', "{{datname}}")], unit="bytes", desc="Size of each database."), 8, 8)
r.add(ts("Transactions/s by database", [tgt(f'sum by (datname) (rate(pg_stat_database_xact_commit{DS}[5m]))', "{{datname}} commit"),
                                        tgt(f'sum by (datname) (rate(pg_stat_database_xact_rollback{DS}[5m]))', "{{datname}} rollback")], unit="ops",
         desc="Commits and rollbacks. Rising rollbacks = application errors or deadlocks."), 8, 8)
r.add(ts("Cache hit by database", [tgt(f'sum by (datname) (rate(pg_stat_database_blks_hit{DS}[5m])) / sum by (datname) (rate(pg_stat_database_blks_hit{DS}[5m]) + rate(pg_stat_database_blks_read{DS}[5m]))', "{{datname}}")],
         unit="percentunit", th=steps((0.9, "yellow"), (0.99, "green"), base="red"), fill=0, desc="99%+ yaxshi."), 8, 8)
r.add(ts("Rows read / written", [tgt(f'sum by (datname) (rate(pg_stat_database_tup_fetched{DS}[5m]))', "{{datname}} fetched"),
                                 tgt(f'sum by (datname) (rate(pg_stat_database_tup_inserted{DS}[5m]))', "{{datname}} inserted"),
                                 tgt(f'sum by (datname) (rate(pg_stat_database_tup_updated{DS}[5m]))', "{{datname}} updated"),
                                 tgt(f'sum by (datname) (rate(pg_stat_database_tup_deleted{DS}[5m]))', "{{datname}} deleted")], unit="rps",
         desc="Rows per second, read and written."), 8, 8)
r.add(ts("Rows returned vs fetched", [tgt(f'sum by (datname) (rate(pg_stat_database_tup_returned{DS}[5m]))', "{{datname}} returned (scanned)"),
                                      tgt(f'sum by (datname) (rate(pg_stat_database_tup_fetched{DS}[5m]))', "{{datname}} fetched (used)")], unit="rps",
         desc="returned (scanned) much larger than fetched = many seq scans, missing index."), 8, 8)
r.add(ts("Temp files & conflicts", [tgt(f'sum by (datname) (rate(pg_stat_database_temp_bytes{DS}[5m]))', "{{datname}} temp bytes/s"),
                                    tgt(f'sum by (datname) (rate(pg_stat_database_conflicts{DS}[5m]))', "{{datname}} conflicts/s")], unit="Bps",
         desc="Temp = sorts/hashes spilled to disk (work_mem too small). Conflicts = queries cancelled on a replica."), 8, 8)
r.end()

# ─────────────────────────────── Tables ───────────────────────────────
r = Row("Tables — size, scans, bloat, vacuum", collapsed=True)
TS = f'{{{I}, {D}}}'
tt = table("Tables overview", [
    tgt(f'pg_table_total_bytes{TS}', instant=True, fmt="table"),
    tgt(f'pg_table_index_bytes{TS}', instant=True, fmt="table"),
    tgt(f'pg_table_live_tuples{TS}', instant=True, fmt="table"),
    tgt(f'pg_table_dead_tuples{TS} / (pg_table_live_tuples{TS} + pg_table_dead_tuples{TS} > 0)', instant=True, fmt="table"),
    tgt(f'rate(pg_table_seq_scan{TS}[$__range])', instant=True, fmt="table"),
    tgt(f'rate(pg_table_idx_scan{TS}[$__range])', instant=True, fmt="table"),
    tgt(f'rate(pg_table_idx_scan{TS}[$__range]) / (rate(pg_table_idx_scan{TS}[$__range]) + rate(pg_table_seq_scan{TS}[$__range]) > 0)', instant=True, fmt="table"),
    tgt(f'rate(pg_table_heap_blks_hit{TS}[$__range]) / (rate(pg_table_heap_blks_hit{TS}[$__range]) + rate(pg_table_heap_blks_read{TS}[$__range]) > 0)', instant=True, fmt="table"),
    tgt(f'rate(pg_table_n_tup_ins{TS}[$__range]) + rate(pg_table_n_tup_upd{TS}[$__range]) + rate(pg_table_n_tup_del{TS}[$__range])', instant=True, fmt="table"),
    tgt(f'rate(pg_table_n_tup_hot_upd{TS}[$__range]) / (rate(pg_table_n_tup_upd{TS}[$__range]) > 0)', instant=True, fmt="table"),
    tgt(f'pg_table_since_vacuum_seconds{TS}', instant=True, fmt="table"),
    tgt(f'pg_table_since_analyze_seconds{TS}', instant=True, fmt="table"),
], desc="Every table. Low index usage + high seq scans/s = missing index. High dead % = VACUUM is behind (bloat). "
        "Low HOT % = updates also write indexes (fillfactor). -1 = never vacuumed/analyzed.",
    sort=("Total size", True),
    rename={"Value #A": "Total size", "Value #B": "Index size", "Value #C": "Live rows", "Value #D": "Dead %", "Value #E": "Seq scans/s",
            "Value #F": "Index scans/s", "Value #G": "Index usage", "Value #H": "Cache hit", "Value #I": "Writes/s", "Value #J": "HOT %",
            "Value #K": "Since vacuum", "Value #L": "Since analyze", "datname": "db", "schemaname": "schema", "relname": "table"},
    order=["db", "schema", "table"],
    overrides=[col("table", width=180), col("Total size", unit="bytes", cell={"type": "gauge", "mode": "basic", "valueDisplayMode": "text"}, decimals=1),
               col("Index size", unit="bytes", decimals=1), col("Live rows", unit="short"),
               col("Dead %", unit="percentunit", cell=BG, th=steps((0.1, "yellow"), (0.2, "red")), decimals=1),
               col("Seq scans/s", unit="short", decimals=2), col("Index scans/s", unit="short", decimals=1),
               col("Index usage", unit="percentunit", cell=TXT, th=steps((0.5, "yellow"), (0.95, "green"), base="red"), decimals=0),
               col("Cache hit", unit="percentunit", cell=TXT, th=steps((0.9, "yellow"), (0.99, "green"), base="red"), decimals=1),
               col("Writes/s", unit="rps", decimals=1), col("HOT %", unit="percentunit", decimals=0),
               col("Since vacuum", unit="s", cell=TXT, th=steps((86400, "yellow"), (604800, "red")), decimals=0),
               col("Since analyze", unit="s", cell=TXT, th=steps((86400, "yellow"), (604800, "red")), decimals=0)])
tt["id"] = P_TABLES
r.add(tt, 24, 10)
r.add(ts("Largest tables", [tgt(f'topk(10, pg_table_total_bytes{TS})', "{{datname}}.{{relname}}")], unit="bytes", desc="10 largest tables (including indexes)."), 8, 8)
r.add(ts("Sequential scans/s (top 10)", [tgt(f'topk(10, rate(pg_table_seq_tup_read{TS}[5m]))', "{{datname}}.{{relname}}")], unit="rps",
         desc="Rows/s read by seq scans. High on a big table = candidate for an index."), 8, 8)
r.add(ts("Dead rows (top 10)", [tgt(f'topk(10, pg_table_dead_tuples{TS})', "{{datname}}.{{relname}}")], desc="Dead rows waiting for VACUUM."), 8, 8)
r.add(ts("Writes by table (top 10)", [tgt(f'topk(10, rate(pg_table_n_tup_ins{TS}[5m]) + rate(pg_table_n_tup_upd{TS}[5m]) + rate(pg_table_n_tup_del{TS}[5m]))', "{{datname}}.{{relname}}")],
         unit="rps", stack=True, desc="Insert+update+delete rows/s."), 12, 8)
r.add(ts("Vacuum & analyze runs", [tgt(f'sum by (datname, relname) (increase(pg_table_vacuum_count{TS}[1h]))', "vacuum {{datname}}.{{relname}}"),
                                   tgt(f'sum by (datname, relname) (increase(pg_table_analyze_count{TS}[1h]))', "analyze {{datname}}.{{relname}}")],
         draw="bars", fill=70, desc="Vacuum/analyze runs per hour."), 12, 8)
r.add(table("Unused indexes (no scans in the selected range)", [
    tgt(f'sum by (datname, relname, indexrelname) (pg_index_size_bytes{{{I}, {D}}}) and on (datname, relname, indexrelname) '
        f'(sum by (datname, relname, indexrelname) (increase(pg_index_idx_scan{{{I}, {D}}}[$__range])) == 0)', instant=True, fmt="table"),
], desc="Indexes no query used: they still cost disk and slow every write. Check over a long range (7d+) before dropping; "
        "unique / primary-key indexes enforce rules even when never scanned.",
    hide=("Time",), rename={"datname": "Database", "relname": "Table", "indexrelname": "Index", "Value": "Size"}, sort=("Size", True),
    overrides=[col("Size", unit="bytes")]), 24, 8)
r.end()

# ─────────────────────────────── Locks ───────────────────────────────
r = Row("Locks & blocking", collapsed=True)
lk = ts("Blocked sessions by service", [tgt(f'sum by (application, datname) (pg_app_blocked_sessions{{{I}, {A}, {D}}})', "{{application}} · {{datname}}")],
        stack=True, draw="bars", fill=70, desc="Sessions waiting on another session's lock. Find the blocker: 'still waiting for' lines in Logs, or "
        "SELECT pid, pg_blocking_pids(pid), query FROM pg_stat_activity WHERE cardinality(pg_blocking_pids(pid)) > 0;")
lk["id"] = P_LOCKS
r.add(lk, 12, 8)
r.add(ts("Longest lock wait by service", [tgt(f'max by (application) (pg_app_blocked_max_wait_seconds{{{I}, {A}, {D}}})', "{{application}}")], unit="s",
         th=steps((10, "yellow"), (60, "red")), fill=0, desc="Lock wait time. Alert: 60 s."), 12, 8)
r.add(ts("Locks by mode", [tgt(f'sum by (mode) (pg_locks_count{{{I}, {D}}}) > 0', "{{mode}}")], stack=True,
         desc="Held locks by mode. AccessExclusiveLock = DDL (ALTER/DROP/VACUUM FULL), blocks everything."), 12, 8)
r.add(ts("Deadlocks", [tgt(f'sum by (datname) (increase(pg_stat_database_deadlocks{{{I}, {D}}}[5m]))', "{{datname}}")], draw="bars", fill=80,
         desc="Deadlocks per 5 minutes. Cause: two transactions update rows in opposite order."), 12, 8)
r.end()

# ─────────────────────────────── Internals ───────────────────────────────
r = Row("Checkpoints, WAL, buffers", collapsed=True)
BW = f'{{{I}}}'
r.add(ts("Checkpoints", [tgt(f'rate(pg_stat_bgwriter_checkpoints_timed_total{BW}[15m]) * 3600', "timed /h"),
                         tgt(f'rate(pg_stat_bgwriter_checkpoints_req_total{BW}[15m]) * 3600', "requested /h")],
         desc="Many requested = max_wal_size too small, checkpoints too frequent (IO bursts)."), 8, 8)
r.add(ts("Buffers written", [tgt(f'rate(pg_stat_bgwriter_buffers_checkpoint_total{BW}[5m]) * 8192', "checkpoint"),
                             tgt(f'rate(pg_stat_bgwriter_buffers_clean_total{BW}[5m]) * 8192', "bgwriter"),
                             tgt(f'rate(pg_stat_bgwriter_buffers_backend_total{BW}[5m]) * 8192', "backend")], unit="Bps", stack=True,
         desc="Who writes to disk. High 'backend' = queries must write themselves (bgwriter is behind)."), 8, 8)
r.add(ts("Checkpoint write / sync time", [tgt(f'rate(pg_stat_bgwriter_checkpoint_write_time_total{BW}[5m]) / 1000', "write"),
                                          tgt(f'rate(pg_stat_bgwriter_checkpoint_sync_time_total{BW}[5m]) / 1000', "sync")], unit="percentunit",
         desc="Share of time spent writing and fsyncing checkpoints. High sync = slow disk."), 8, 8)
r.add(ts("Buffers allocated", [tgt(f'rate(pg_stat_bgwriter_buffers_alloc_total{BW}[5m]) * 8192', "allocated")], unit="Bps",
         desc="Buffer allocation rate: data entering shared_buffers."), 8, 8)
r.add(ts("WAL size", [tgt(f'pg_wal_size_bytes{BW}', "pg_wal directory")], unit="bytes", desc="Size of pg_wal. Constant growth = a stuck replication slot or archiving."), 8, 8)
r.add({"type": "table", "title": "Key settings", "datasource": VM, "description": "Key settings (pg_settings).",
       "targets": refs([tgt(f'{{__name__=~"pg_settings_({k})", {I}}}', instant=True, fmt="table") for k in
                        ["max_connections|shared_buffers_bytes|effective_cache_size_bytes|work_mem_bytes|maintenance_work_mem_bytes|max_wal_size_bytes|random_page_cost|autovacuum_max_workers|max_parallel_workers|checkpoint_timeout_seconds"]]),
       "transformations": [{"id": "organize", "options": {"excludeByName": {"Time": True, "job": True, "instance": True, "server": True}, "renameByName": {"__name__": "setting", "Value": "value"}}}],
       "fieldConfig": {"defaults": {"custom": {"cellOptions": {"type": "auto"}}}, "overrides": []},
       "options": {"showHeader": True, "cellHeight": "sm"}}, 8, 8)
r.end()

r = Row("Replication, vacuum & wraparound", collapsed=True)
rp = ts("XID age by database", [tgt(f'max by (datname) (pg_database_wraparound_age_datfrozenxid_seconds{{{I}, {D}}})', "{{datname}}")],
        th=steps((500000000, "yellow"), (1000000000, "red")), fill=0,
        desc="Age of the oldest unfrozen transaction. At ~2.1 billion the database stops writes. Alert: 1 billion.")
rp["id"] = P_REPL
r.add(rp, 8, 8)
r.add(ts("Replication lag", [tgt(f'max(pg_replication_lag_seconds{{{I}}})', "lag"), tgt(f'max(pg_replication_is_replica{{{I}}})', "is replica")], unit="s",
         th=steps((10, "yellow"), (30, "red")), fill=0, desc="Meaningful on replicas only; 0 on a primary."), 8, 8)
r.add(ts("Oldest transaction (any)", [tgt(f'max(pg_long_running_transactions_oldest_timestamp_seconds{{{I}}})', "oldest"),
                                      tgt(f'max(pg_long_running_transactions{{{I}}})', "count > 5 min")], unit="s", fill=0,
         desc="Oldest transaction on the server (blocks autovacuum)."), 8, 8)
r.end()

r = Row("Postgres alerts", collapsed=True)
al = {"type": "table", "title": "Firing & pending alerts", "datasource": VM, "id": P_ALERTS,
      "description": "Postgres* alerts firing or pending now. Full list: Alerts dashboard.",
      "targets": refs([tgt('ALERTS{alertname=~"Postgres.*"}', instant=True, fmt="table")]),
      "transformations": [{"id": "organize", "options": {"excludeByName": {"Time": True, "Value": True, "__name__": True, "job": True}}}],
      "fieldConfig": {"defaults": {"custom": {"cellOptions": {"type": "auto"}}}, "overrides": [
          col("alertstate", cell=BG, th=steps(base="red")),
          {"matcher": {"id": "byName", "options": "alertstate"}, "properties": [{"id": "mappings", "value": [{"type": "value", "options": {"firing": {"color": "red"}, "pending": {"color": "orange"}}}]}]}]},
      "options": {"showHeader": True, "cellHeight": "sm"}}
r.add(al, 24, 7)
r.end()

dash = {
    "title": "PostgreSQL",
    "uid": "postgres",
    "description": "PostgreSQL: health, per-service (application_name) load and latency p50/p95/p99, top and slow queries, logs, databases, tables, locks, WAL, vacuum. Data: postgres-exporter + statement log (Vector).",
    "tags": ["postgres", "database", "sql", "services"],
    "schemaVersion": 39,
    "editable": True,
    "graphTooltip": 1,
    "refresh": "30s",
    "time": {"from": "now-3h", "to": "now"},
    "timepicker": {"refresh_intervals": ["10s", "30s", "1m", "5m", "15m"]},
    "fiscalYearStartMonth": 0,
    "liveNow": False,
    "links": [{"title": "Related", "type": "dashboards", "asDropdown": True, "tags": ["postgres"], "includeVars": False, "keepTime": True}] + nav_links("postgres"),
    "annotations": {"list": [
        {"builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"}, "enable": True, "hide": True, "iconColor": "rgba(0, 211, 255, 1)", "name": "Annotations & Alerts", "type": "dashboard"},
        {"name": "Postgres alerts", "datasource": VM, "enable": True, "iconColor": "red",
         "expr": 'ALERTS{alertname=~"Postgres.*", alertstate="firing"}', "step": "60s", "titleFormat": "{{alertname}}", "textFormat": "{{datname}} {{application}} {{pg_app}}", "useValueForTime": False},
        {"name": "PostgreSQL restart", "datasource": VM, "enable": True, "iconColor": "orange",
         "expr": 'changes(pg_postmaster_start_time_seconds[2m]) > 0', "step": "60s", "titleFormat": "PostgreSQL restarted"},
    ]},
    "templating": {"list": [
        project_var(),
        {"name": "instance", "label": "Server", "type": "query", "datasource": VM, "query": {"query": 'label_values(pg_up{project=~"$project"}, instance)', "refId": "q"},
         "refresh": 2, "includeAll": False, "multi": False, "sort": 1, "description": "postgres-exporter target (one PostgreSQL server)."},
        {"name": "datname", "label": "Database", "type": "query", "datasource": VM,
         "query": {"query": 'label_values(pg_stat_database_numbackends{instance=~"$instance", datname!~"template.*"}, datname)', "refId": "q"},
         "refresh": 2, "includeAll": True, "allValue": ".*", "multi": True, "sort": 1, "current": {"text": "All", "value": "$__all"}},
        {"name": "application", "label": "Service (application_name)", "type": "query", "datasource": VM,
         "query": {"query": 'label_values(pg_app_activity_count{instance=~"$instance"}, application)', "refId": "q"},
         "refresh": 2, "includeAll": True, "allValue": ".*", "multi": True, "sort": 1, "current": {"text": "All", "value": "$__all"},
         "description": "application_name from the app's connection string. Clicking a service name in a table sets it too."},
    ]},
    "panels": panels,
}
json.dump(dash, open(os.path.join(ROOT, "Apps", "postgres.json"), "w"), indent=2, ensure_ascii=False)
print("Apps/postgres.json panels:", sum(1 + len(p.get("panels", [])) for p in panels))

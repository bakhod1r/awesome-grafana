"""Shared helpers for the dashboard generators in this folder.

Every dashboard JSON under grafana/dashboards/ that has a generator here is built from Python,
so layout, colours and descriptions stay consistent. Edit the generator, then run:

    python3 grafana/generators/build.py          # rebuild every generated dashboard
    python3 scripts/check-dashboards.py          # run every panel query against the live stack, list "No data"

Grafana re-reads the files on its own (provisioning), no restart needed.
"""
import json
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "dashboards"))

VM = {"type": "prometheus", "uid": "victoriametrics"}
VL = {"type": "victoriametrics-logs-datasource", "uid": "victorialogs"}
TEMPO = {"type": "tempo", "uid": "tempo"}
AM = {"type": "alertmanager", "uid": "alertmanager"}

BG = {"type": "color-background", "mode": "gradient"}
TXT = {"type": "color-text"}
GAUGE = {"type": "gauge", "mode": "lcd", "valueDisplayMode": "text"}
BAR = {"type": "gauge", "mode": "basic", "valueDisplayMode": "text"}

# Same top links on every dashboard: one click to any other one, keeping the time range.
NAV = [
    ("Home", "overview", "overview", "apps"),
    ("Docker", "docker-projects", "docker-projects", "docker"),
    ("Node", "node-overview", "node-overview", "dashboard"),
    ("Services", "services", "services", "dashboard"),
    ("PostgreSQL", "postgres", "postgresql", "dashboard"),
    ("Logs", "logs", "logs", "doc"),
    ("Traces", "traces", "traces", "dashboard"),
    ("Alerts", "alerts", "alerts", "bolt"),
    ("SLO", "probes-slo", "probes-slo", "dashboard"),
    ("App SLO", "app-slo", "app-slo", "dashboard"),
    ("Stack", "self", "self", "cloud"),
]


# Event markers shared by every dashboard (build.py also adds them to the hand-written ones):
#   Container (re)started  a container started less than a minute ago (crash, restart or recreate)
#   New image deployed     a container runs an image it did not run 10 minutes ago: a deploy or rollback
#   Deploys                annotations tagged "deploy" posted to Grafana by scripts/annotate-deploy.sh (CI, by hand)
EVENT_ANNOTATIONS = [
    {"name": "Container (re)started", "datasource": VM, "enable": True, "iconColor": "blue",
     "expr": 'count by (name) (time() - container_start_time_seconds{name!=""} < 60)', "step": "60s",
     "titleFormat": "started: {{name}}"},
    {"name": "New image deployed", "datasource": VM, "enable": True, "iconColor": "purple",
     "expr": '(count by (name, image) (container_last_seen{name!="", image!=""}) unless count by (name, image) (container_last_seen{name!="", image!=""} offset 10m))'
             ' and on (name) (time() - container_start_time_seconds{name!=""} < 120)',
     "step": "60s", "titleFormat": "deploy: {{name}}", "textFormat": "{{image}}"},
    {"name": "Deploys", "datasource": {"type": "grafana", "uid": "-- Grafana --"}, "enable": True, "iconColor": "purple",
     "target": {"type": "tags", "tags": ["deploy"], "matchAny": True, "limit": 100}},
]


def nav_links(skip=None):
    out = []
    for title, uid, slug, icon in NAV:
        if uid == skip:
            continue
        out.append({"title": title, "type": "link", "icon": icon, "url": f"/d/{uid}/{slug}?${{__url_time_range}}", "targetBlank": False})
    return out


# Graphs with a legend table need room: three per line squeezes the plot and cuts the table.
# widen_graphs() gives graphs with a right-side table legend the full width, turns other graphs narrower
# than half the screen into half-width, taller ones, and re-flows the section left to right. build.py runs it on every dashboard, so generators
# and hand-written JSON follow the same rule. Graphs next to a wider graph are left alone.
GRAPH_W, GRAPH_H = 12, 10


def _graph_to_widen(p, line):
    """Target width for a graph that is too narrow for its legend, or None.
    A table legend on the right eats half the panel: such graphs get the full width.
    Other graphs with a legend narrower than half the screen get half the screen."""
    lg = p.get("options", {}).get("legend", {})
    if p.get("type") != "timeseries" or lg.get("displayMode") == "hidden" or lg.get("showLegend") is False:
        return None
    w = p["gridPos"]["w"]
    if lg.get("displayMode") == "table" and lg.get("placement") == "right" and w < 24:
        return 24
    if not 7 <= w < GRAPH_W:
        return None
    return None if any(q.get("type") == "timeseries" and q["gridPos"]["w"] >= GRAPH_W for q in line) else GRAPH_W


def _reflow(section):
    """Widen graphs in one section (panels between two rows); return how many grid units it grew."""
    if not section:
        return 0
    section.sort(key=lambda p: (p["gridPos"]["y"], p["gridPos"]["x"]))
    lines = {}
    for p in section:
        lines.setdefault(p["gridPos"]["y"], []).append(p)
    todo = [(p, w) for line in lines.values() for p in line for w in [_graph_to_widen(p, line)] if w]
    if not todo:
        return 0
    top = section[0]["gridPos"]["y"]
    old_end = max(p["gridPos"]["y"] + p["gridPos"]["h"] for p in section)
    for p, w in todo:
        p["gridPos"]["w"], p["gridPos"]["h"] = w, max(p["gridPos"]["h"], GRAPH_H)
    lines, x = [[]], 0
    for p in section:
        if x + p["gridPos"]["w"] > 24:
            lines.append([])
            x = 0
        lines[-1].append(p)
        x += p["gridPos"]["w"]
    y = top
    for line in lines:  # same height on a line, last panel fills the leftover width: no holes
        h = max(p["gridPos"]["h"] for p in line)
        x = 0
        for p in line:
            p["gridPos"].update(x=x, y=y, h=h)
            x += p["gridPos"]["w"]
        line[-1]["gridPos"]["w"] += 24 - x
        y += h
    return y - old_end


def widen_graphs(d):
    panels = sorted(d.get("panels", []), key=lambda p: (p["gridPos"]["y"], p["gridPos"]["x"]))
    section, shift = [], 0
    for p in panels + [None]:
        if p is not None and p["type"] != "row":
            p["gridPos"]["y"] += shift
            section.append(p)
            continue
        shift += _reflow(section)
        section = []
        if p is not None:
            p["gridPos"]["y"] += shift
            inner = p.get("panels", [])
            for q in inner:
                q["gridPos"]["y"] += shift
            _reflow(inner)  # collapsed row: Grafana places these itself when the row opens


def steps(*pairs, base="green"):
    s = [{"color": base, "value": None}]
    for v, c in pairs:
        s.append({"color": c, "value": v})
    return {"mode": "absolute", "steps": s}


def tgt(expr, legend="", instant=False, fmt=None, ds=VM, **kw):
    t = {"refId": "A", "expr": expr, "legendFormat": legend, "datasource": ds}
    if instant:
        t["instant"] = True
        t["range"] = False
    if fmt:
        t["format"] = fmt
    t.update(kw)
    return t


def refs(ts):
    for i, t in enumerate(ts):
        t["refId"] = chr(65 + i) if i < 26 else "A" + chr(65 + i - 26)
    return ts


class Dash:
    def __init__(self, uid, title, description, tags, time_from="now-6h", refresh="30s", variables=(), annotations=(), links=None):
        self.uid, self.title = uid, title
        self.panels = []
        self.y = 0
        self.cur = None
        self._id = 0
        self.d = {
            "title": title, "uid": uid, "description": description, "tags": list(tags),
            "schemaVersion": 39, "editable": True, "graphTooltip": 1, "refresh": refresh,
            "time": {"from": time_from, "to": "now"},
            "timepicker": {"refresh_intervals": ["10s", "30s", "1m", "5m", "15m"]},
            "links": (links if links is not None else []) + nav_links(uid),
            "annotations": {"list": [
                {"builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"}, "enable": True, "hide": True,
                 "iconColor": "rgba(0, 211, 255, 1)", "name": "Annotations & Alerts", "type": "dashboard"},
                {"name": "Critical alerts", "datasource": VM, "enable": True, "iconColor": "red",
                 "expr": 'ALERTS{alertstate="firing", severity="critical"}', "step": "60s",
                 "titleFormat": "{{alertname}}", "textFormat": "{{instance}} {{name}} {{service}}"},
            ] + EVENT_ANNOTATIONS + list(annotations)},
            "templating": {"list": list(variables)},
            "panels": self.panels,
        }

    def nid(self):
        self._id += 1
        return self._id

    def row(self, title, collapsed=False):
        self.end()
        p = {"type": "row", "id": self.nid(), "title": title, "collapsed": collapsed,
             "gridPos": {"x": 0, "y": self.y, "w": 24, "h": 1}, "panels": []}
        self.panels.append(p)
        self.y += 1
        self.cur = p
        self.x = 0
        self.rowh = 0
        return self

    def add(self, p, w, h):
        if self.cur is None:
            self.row("Overview")
        if self.x + w > 24:
            self.y += self.rowh
            self.x = 0
            self.rowh = 0
        if not p.get("id"):
            p["id"] = self.nid()
        p["gridPos"] = {"x": self.x, "y": self.y, "w": w, "h": h}
        self.x += w
        self.rowh = max(self.rowh, h)
        (self.cur["panels"] if self.cur["collapsed"] else self.panels).append(p)
        return p

    def end(self):
        if self.cur is not None:
            self.y += self.rowh
            self.rowh = 0
            self.x = 0

    def write(self, rel):
        self.end()
        path = os.path.join(ROOT, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.d, f, indent=2, ensure_ascii=False)
            f.write("\n")
        n = sum(1 + len(p.get("panels", [])) for p in self.panels)
        print(f"{rel}: {n} panels")


def query_var(name, label, query, multi=True, include_all=True, desc="", hide=0, all_value=".*", ds=VM):
    v = {"name": name, "label": label, "type": "query", "datasource": ds, "query": {"query": query, "refId": name},
         "refresh": 2, "includeAll": include_all, "multi": multi, "sort": 1, "description": desc, "hide": hide,
         "allowCustomValue": False}  # a stale value in the URL (gone container, renamed service) falls back to the default
    if include_all:
        if all_value is not None:  # None: "All" = the listed values only
            v["allValue"] = all_value
        v["current"] = {"text": "All", "value": "$__all"}
    return v


def project_var():
    """Hidden filter set by links from Docker projects (var-project=shop): the Server list then
    only offers exporters discovered in that compose project. Default .* keeps every server."""
    return {"name": "project", "label": "Project", "type": "textbox", "query": ".*", "hide": 2,
            "current": {"text": ".*", "value": ".*"}}


PJ = "container_label_com_docker_compose_project"
SV = "container_label_com_docker_compose_service"
CONTAINER_LABELS = ("type", "lang", "team", "env")  # container.* Docker labels → container_label_container_* in cAdvisor

# container.type → dashboard uid. Regexes match "<type>|<image>", so db can pick PostgreSQL or MySQL from the image.
TYPE_ROUTES = [("endpoints", "(backend|service|api)"), ("frontend", "frontend"), ("postgres", "db\\\\|.*postgres.*"),
               ("mysql", "db\\\\|.*(mysql|mariadb).*"), ("redis", "cache"), ("storage", "storage"),
               ("queue", "queue"), ("worker", "worker"), ("proxy", "proxy"), ("search", "search"), ("nosql", "nosql"),
               ("cron", "cron"), ("self", "monitoring")]
DASH_NAMES = {"container": "Container", "endpoints": "App Endpoints", "frontend": "Frontend", "postgres": "PostgreSQL",
              "mysql": "MySQL", "redis": "Redis", "storage": "Storage", "queue": "Queue", "worker": "Worker", "proxy": "Proxy",
              "search": "Search", "nosql": "NoSQL", "cron": "Cron", "self": "Self Monitoring"}


def R(e, dst, rep, src, rx):
    return f'label_replace({e}, "{dst}", "{rep}", "{src}", "{rx}")'


def type_routing(e):
    """cAdvisor series (by compose labels, name, image, container_label_container_*) → plus labels
    project, service, type/lang/team/env, dash (uid to open), lsvc (its service var), pj (raw compose project),
    link_dash / link_name (for links: visible columns have display names) and opens (readable text)."""
    e = R(e, "project", "$1", PJ, "(.+)")
    e = R(e, "project", "(standalone)", PJ, "")
    e = R(e, "service", "$1", "name", "(.+)")
    e = R(e, "service", "$1", SV, "(.+)")
    for l in CONTAINER_LABELS:
        e = R(e, l, "$1", f"container_label_container_{l}", "(.+)")
    e = f'label_join({e}, "key", "|", "type", "image")'
    e = R(e, "dash", "container", "name", ".*")  # default: the Container dashboard
    for dash, rx in TYPE_ROUTES:
        e = R(e, "dash", dash, "key", rx if "|" in rx and "\\" in rx else f"{rx}\\\\|.*")
    e = f'label_join({e}, "appsvc", "-", "project", "service")'
    e = R(e, "lsvc", "$1", "service", "(.+)")
    e = f'label_join({e}, "k2", "|", "dash", "appsvc")'
    e = R(e, "lsvc", "$1", "k2", "endpoints\\\\|(.+)")
    e = R(e, "pj", "$1", PJ, "(.*)")
    e = R(e, "link_dash", "$1", "dash", "(.*)")
    e = R(e, "link_name", "$1", "name", "(.*)")
    e = R(e, "opens", "$1", "dash", "(.*)")
    for uid, text in DASH_NAMES.items():
        e = R(e, "opens", text, "dash", uid)
    return e


def container_var():
    """Hidden filter set by links from Docker projects / Project (var-container=<name>). Default .* = all."""
    return {"name": "container", "label": "Container", "type": "textbox", "query": ".*", "hide": 2,
            "current": {"text": ".*", "value": ".*"}}


def type_logs(types):
    """LogsQL stream filter: containers of these types, or the one container picked via var-container."""
    return f'type:~"^({types})$" container:~"^${{container:raw}}$"'


def health_row(d, types, title="Container health"):
    """Same first row on every type dashboard: is the container up, restarting, near its limits.
    Opened without var-container, it covers every container labelled with one of `types` (regex)."""
    n = f'name=~"$container", name!="", container_label_container_type=~"{types}"'
    d.row(title)
    d.add(stat("Running", f"count(time() - container_last_seen{{{n}}} < 60) or vector(0)", color_mode="value", graph=False,
               th=steps(base="blue"), desc="Containers seen by cAdvisor in the last minute."), 4, 4)
    d.add(stat("Restarts (24h)", f"sum(resets(container_cpu_usage_seconds_total{{{n}}}[24h])) or vector(0)", graph=False,
               th=steps((1, "orange"), (5, "red"))), 4, 4)
    d.add(stat("OOM kills (24h)", f"sum(increase(container_oom_events_total{{{n}}}[24h])) or vector(0)", graph=False,
               th=steps((1, "red")), desc="Killed by the kernel for using more memory than the limit."), 4, 4)
    d.add(stat("CPU (cores)", f"sum(rate(container_cpu_usage_seconds_total{{{n}}}[5m]))", decimals=2, color_mode="value", th=steps(base="blue")), 4, 4)
    d.add(stat("Memory", f"sum(container_memory_working_set_bytes{{{n}}})", unit="bytes", color_mode="value", th=steps(base="blue")), 4, 4)
    d.add(stat("Memory vs limit", f"max(container_memory_working_set_bytes{{{n}}} / (container_spec_memory_limit_bytes{{{n}}} > 0)) * 100",
               unit="percent", decimals=0, th=steps((80, "orange"), (95, "red")),
               desc="Highest working set vs memory limit among the containers. Empty when none has a limit."), 4, 4)
    d.panels[-1]["fieldConfig"]["defaults"]["noValue"] = "No memory limit set"


def text(md, title=""):
    return {"type": "text", "title": title, "transparent": True, "options": {"mode": "markdown", "content": md}}


def stat(title, expr, unit="short", th=None, desc="", decimals=None, mappings=None, link=None, color_mode="background",
         text_mode="value", legend="", graph=True, ds=VM, calc="lastNotNull", instant=True):
    p = {"type": "stat", "title": title, "description": desc, "datasource": ds,
         "targets": [tgt(expr, legend, instant=instant, ds=ds)],
         "options": {"reduceOptions": {"calcs": [calc], "fields": "", "values": False},
                     "colorMode": color_mode, "graphMode": "area" if graph else "none", "textMode": text_mode,
                     "justifyMode": "center", "wideLayout": True},
         "fieldConfig": {"defaults": {"unit": unit, "thresholds": th or steps(), "color": {"mode": "thresholds"},
                                      "mappings": mappings or [], "links": [link] if link else []}, "overrides": []}}
    if decimals is not None:
        p["fieldConfig"]["defaults"]["decimals"] = decimals
    return p


def ts(title, targets, unit="short", desc="", stack=False, fill=10, th=None, legend_calcs=("mean", "max", "lastNotNull"),
       draw="line", minv=None, maxv=None, overrides=None, links=None, ds=VM, legend="table", percent=False):
    p = {"type": "timeseries", "title": title, "description": desc, "datasource": ds, "targets": refs(targets),
         "fieldConfig": {"defaults": {"unit": unit, "color": {"mode": "palette-classic-by-name"},
                                      "custom": {"drawStyle": draw, "lineWidth": 2 if draw == "line" else 1, "fillOpacity": fill,
                                                 "gradientMode": "opacity", "showPoints": "never", "spanNulls": True,
                                                 "stacking": {"mode": "percent" if percent else ("normal" if stack else "none"), "group": "A"},
                                                 "thresholdsStyle": {"mode": "dashed" if th else "off"}},
                                      "thresholds": th or steps(), "links": links or []},
                         "overrides": overrides or []},
         "options": {"legend": {"displayMode": legend, "placement": "bottom" if legend == "table" else "right",
                                "calcs": list(legend_calcs) if legend == "table" else [], "showLegend": legend != "hidden"},
                     "tooltip": {"mode": "multi", "sort": "desc"}}}
    if minv is not None:
        p["fieldConfig"]["defaults"]["min"] = minv
    if maxv is not None:
        p["fieldConfig"]["defaults"]["max"] = maxv
    return p


def compare_week(title, expr, legend, unit="short", desc=""):
    """Now vs the same time one week ago, dashed: anomalies stand out."""
    return ts(title, [tgt(expr, legend), tgt(f"({expr}) offset 1w", legend + " (1 week ago)")], unit=unit, desc=desc, fill=0,
              overrides=[{"matcher": {"id": "byRegexp", "options": ".*1 week ago.*"}, "properties": [
                  {"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [6, 6]}}, {"id": "custom.lineWidth", "value": 1},
                  {"id": "color", "value": {"mode": "fixed", "fixedColor": "#8e8e8e"}}]}])


def table(title, targets, desc="", overrides=None, sort=None, hide=(), rename=None, order=None, unit=None, merge=True, ds=VM, links=None):
    exclude = {k: True for k in ("Time", "__name__", "job", "instance", "server") + tuple(hide) if k not in (rename or {})}  # renamed = wanted
    org = {"excludeByName": exclude, "renameByName": rename or {}, "indexByName": {k: i for i, k in enumerate(order or [])}}
    tr = ([{"id": "merge", "options": {}}] if merge else []) + [{"id": "organize", "options": org}]
    p = {"type": "table", "title": title, "description": desc, "datasource": ds, "targets": refs(targets),
         "transformations": tr,
         "fieldConfig": {"defaults": {"custom": {"align": "auto", "cellOptions": {"type": "auto"}, "filterable": True},
                                      "thresholds": steps(), "links": links or []}, "overrides": overrides or []},
         "options": {"showHeader": True, "cellHeight": "sm", "footer": {"show": False},
                     "sortBy": [{"displayName": sort[0], "desc": sort[1]}] if sort else []}}
    if unit:
        p["fieldConfig"]["defaults"]["unit"] = unit
    return p


def col(name, unit=None, cell=None, th=None, width=None, decimals=None, links=None, minv=None, maxv=None, mappings=None, regex=False):
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
    if mappings:
        props.append({"id": "mappings", "value": mappings})
    return {"matcher": {"id": "byRegexp" if regex else "byName", "options": name}, "properties": props}


def vmap(d):
    """{"0": ("DOWN", "red"), ...} → Grafana value mappings."""
    return [{"type": "value", "options": {k: {"text": t, "color": c, "index": i} for i, (k, (t, c)) in enumerate(d.items())}}]


def logs(title, expr, desc=""):
    return {"type": "logs", "title": title, "description": desc, "datasource": VL,
            "targets": [{"refId": "A", "datasource": VL, "queryType": "instant", "expr": expr}],
            "options": {"showTime": True, "wrapLogMessage": True, "sortOrder": "Descending", "enableLogDetails": True,
                        "prettifyLogMessage": False, "dedupStrategy": "none", "showLabels": False, "showCommonLabels": False}}


def vl_ts(title, expr, legend, desc="", unit="short", stack=True, draw="bars"):
    p = ts(title, [], unit=unit, desc=desc, stack=stack, draw=draw, fill=80 if draw == "bars" else 10, legend_calcs=("sum",))
    p["datasource"] = VL
    p["targets"] = [{"refId": "A", "datasource": VL, "queryType": "statsRange", "expr": expr, "legendFormat": legend}]
    return p


def VL_TABLE_TRANSFORMS(organize=None):
    """VictoriaLogs stats return one frame per group (labels + one value per stat): turn the labels into
    columns, name each value after its stat (count() hits → "hits") and merge everything into one table.
    Without this Grafana shows a frame picker ("hits{_msg=...}") instead of a table."""
    org = organize or {"excludeByName": {"Time": True}}
    return [{"id": "labelsToFields", "options": {"mode": "columns", "valueLabel": "__name__"}},
            {"id": "merge", "options": {}},
            {"id": "organize", "options": org}]


def vl_table(title, expr, desc="", overrides=None, sort=None):
    return {"type": "table", "title": title, "description": desc, "datasource": VL,
            "targets": [{"refId": "A", "datasource": VL, "queryType": "stats", "expr": expr}],
            "transformations": VL_TABLE_TRANSFORMS(),
            "fieldConfig": {"defaults": {"custom": {"filterable": True, "cellOptions": {"type": "auto"}}}, "overrides": overrides or []},
            "options": {"showHeader": True, "cellHeight": "sm", "sortBy": [{"displayName": sort[0], "desc": sort[1]}] if sort else []}}


def state_timeline(title, targets, desc="", mappings=None, th=None, unit="short"):
    return {"type": "state-timeline", "title": title, "description": desc, "datasource": VM, "targets": refs(targets),
            "fieldConfig": {"defaults": {"unit": unit, "color": {"mode": "thresholds"}, "thresholds": th or steps(),
                                         "mappings": mappings or [], "custom": {"fillOpacity": 80, "lineWidth": 0}}, "overrides": []},
            "options": {"showValue": "never", "mergeValues": True, "rowHeight": 0.85, "alignValue": "left",
                        "legend": {"showLegend": False}, "tooltip": {"mode": "single"}}}


def heatmap(title, expr, desc="", unit="s", fmt="heatmap", calculate=False, legend="{{le}}"):
    return {"type": "heatmap", "title": title, "description": desc, "datasource": VM,
            "targets": [{"refId": "A", "datasource": VM, "expr": expr, "format": fmt, "legendFormat": legend}],
            "options": {"calculate": calculate, "yAxis": {"unit": unit}, "cellGap": 1,
                        "color": {"mode": "scheme", "scheme": "Turbo", "steps": 64, "exponent": 0.5, "scale": "exponential"},
                        "tooltip": {"mode": "single", "yHistogram": True}, "legend": {"show": True}, "rowsFrame": {"layout": "auto"}}}


def bargauge(title, targets, unit="short", th=None, desc="", maxv=None, minv=0, orientation="horizontal", mode="gradient"):
    p = {"type": "bargauge", "title": title, "description": desc, "datasource": VM, "targets": refs(targets),
         "options": {"orientation": orientation, "displayMode": mode, "showUnfilled": True, "valueMode": "color",
                     "namePlacement": "left", "sizing": "auto", "minVizHeight": 12, "maxVizHeight": 24,
                     "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}},
         "fieldConfig": {"defaults": {"unit": unit, "thresholds": th or steps(), "color": {"mode": "thresholds"}, "min": minv}, "overrides": []}}
    if maxv is not None:
        p["fieldConfig"]["defaults"]["max"] = maxv
    return p


def piechart(title, targets, unit="short", desc="", donut=True):
    return {"type": "piechart", "title": title, "description": desc, "datasource": VM, "targets": refs(targets),
            "options": {"pieType": "donut" if donut else "pie", "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                        "legend": {"displayMode": "table", "placement": "right", "values": ["value", "percent"], "showLegend": True},
                        "tooltip": {"mode": "single"}},
            # palette-classic, not -by-name: the by-name palette crashes the pie chart in Grafana 11.6 ("An unexpected error happened")
            "fieldConfig": {"defaults": {"unit": unit, "color": {"mode": "palette-classic"}}, "overrides": []}}


def dashlist(title, tags=(), query="", desc=""):
    return {"type": "dashlist", "title": title, "description": desc,
            "options": {"showStarred": False, "showRecentlyViewed": False, "showSearch": True, "showHeadings": True,
                        "includeVars": False, "keepTime": True, "query": query, "tags": list(tags), "maxItems": 30}}


def view(dash_uid, slug, pid, title):
    return {"title": title, "url": f"/d/{dash_uid}/{slug}?${{__url_time_range}}&${{__all_variables}}&viewPanel={pid}"}


def goto(dash_uid, slug, title, params=""):
    return {"title": title, "url": f"/d/{dash_uid}/{slug}?${{__url_time_range}}{params}"}

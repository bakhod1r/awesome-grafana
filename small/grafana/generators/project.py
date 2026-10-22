"""Project: one compose project at a glance — summary, its containers, and a click-through per container.

Opened from Docker Projects (click a project name). Clicking a container opens the dashboard that fits its
container.type label (same routing as "Containers by type" on Docker Projects); the lang column opens the
Container dashboard (HTTP + Runtime rows) for container.lang. Containers started without compose show up as "(standalone)".
"""
from lib import *

UID, SLUG = "project", "project"
L = CONTAINER_LABELS
SEL = f'name!="", {PJ}=~"$project"'
HOST_RAM = "max(last_over_time(machine_memory_bytes[1h]))"


def per_name(expr):
    """Value per container, keyed only by name, so the table merge lines them up with the info query."""
    return f"max by (name) ({expr})"


# Info query: one row per container with its labels and where a click goes (type_routing in lib.py).
by = ", ".join([PJ, SV, "name", "image"] + [f"container_label_container_{l}" for l in L])
info = type_routing(f"max by ({by}) (container_last_seen{{{SEL}}})")

OPEN = {"title": "Open the dashboard for this container (by container.type)",
        "url": "/d/${__data.fields.link_dash}?${__url_time_range}&var-project=${__data.fields.pj}&var-service=${__data.fields.lsvc}&var-container=${__data.fields.link_name}"}
RUNTIME = {"title": "Runtime: ${__data.fields.lang}",
           "url": "/d/container/container?${__url_time_range}&var-project=${__data.fields.pj}&var-container=${__data.fields.link_name}"}

def named(c, display):
    c["properties"].append({"id": "displayName", "value": display})
    return c


def hidden(field):
    return {"matcher": {"id": "byName", "options": field}, "properties": [{"id": "custom.hidden", "value": True}]}


# Project picker: text = name, value = regex for the compose label ("^$" = containers without compose).
pv = f'max by (pj, project) ({R(R(R(R(f"container_last_seen{{name!=\"\"}}", "project", "$1", PJ, "(.+)"), "project", "(standalone)", PJ, ""), "pj", "$1", PJ, "(.+)"), "pj", "^$", PJ, "")})'
project_var = {"name": "project", "label": "Project", "type": "query", "datasource": VM,
               "query": {"query": f"query_result({pv})", "refId": "project"},
               "regex": '/pj="(?<value>[^"]+)",project="(?<text>[^"]+)"/', "refresh": 2, "includeAll": False, "multi": False,
               "sort": 1, "description": "Compose project. (standalone) = containers started without compose."}

d = Dash(UID, "Project", "One compose project: summary, every container with its labels, and a click-through per container "
         "to the dashboard that fits its container.type (backend, frontend, db, cache, storage) or its runtime (container.lang).",
         ["docker", "project", "services"], time_from="now-6h", variables=[project_var])

d.row("Summary")
d.add(stat("Containers running", f"count(time() - container_last_seen{{{SEL}}} < 60) or vector(0)", color_mode="value", th=steps(base="blue"), graph=False), 3, 4)
d.add(stat("Restarts (24h)", f"sum(resets(container_cpu_usage_seconds_total{{{SEL}}}[24h])) or vector(0)", th=steps((1, "orange"), (5, "red")), graph=False,
           desc="Container restarts (CPU counter resets) in the last 24h."), 3, 4)
d.add(stat("CPU (cores)", f"sum(rate(container_cpu_usage_seconds_total{{{SEL}}}[5m]))", decimals=2, color_mode="value", th=steps(base="blue")), 3, 4)
d.add(stat("Memory", f"sum(container_memory_working_set_bytes{{{SEL}}})", unit="bytes", color_mode="value", th=steps(base="blue")), 3, 4)
d.add(stat("RAM % of host", f"sum(container_memory_working_set_bytes{{{SEL}}}) / {HOST_RAM} * 100", unit="percent", decimals=1,
           th=steps((50, "orange"), (80, "red"))), 3, 4)
d.add(stat("Net in / out", f"sum(rate(container_network_receive_bytes_total{{{SEL}}}[5m])) + sum(rate(container_network_transmit_bytes_total{{{SEL}}}[5m]))",
           unit="Bps", color_mode="value", th=steps(base="blue"), desc="Received + sent per second."), 3, 4)
d.add(stat("Error logs/min", 'sum(rate(vector_log_lines_total{project=~"$project", level=~"error|fatal|panic"}[5m])) * 60 or vector(0)',
           decimals=1, th=steps((1, "orange"), (10, "red")), desc="error, fatal and panic log lines per minute."), 3, 4)
d.add(stat("Firing alerts", f'count(ALERTS{{alertstate="firing", {SEL}}}) or vector(0)', th=steps((1, "red")), graph=False,
           desc="Container alerts (memory, restarts, gone) firing for this project."), 3, 4)

d.row("Containers — click one to open its dashboard")
t = table("Containers", [
    tgt(info, instant=True, fmt="table"),
    tgt(per_name(f"time() - container_last_seen{{{SEL}}} < bool 60"), instant=True, fmt="table"),
    tgt(per_name(f"time() - container_start_time_seconds{{{SEL}}}"), instant=True, fmt="table"),
    tgt(per_name(f"rate(container_cpu_usage_seconds_total{{{SEL}}}[5m])") + " * 100", instant=True, fmt="table"),
    tgt(per_name(f"container_memory_working_set_bytes{{{SEL}}}"), instant=True, fmt="table"),
    tgt(per_name(f"resets(container_cpu_usage_seconds_total{{{SEL}}}[24h])"), instant=True, fmt="table"),
    tgt(R('sum by (container) (rate(vector_log_lines_total{project=~"$project", level=~"error|fatal|panic"}[5m])) * 60',
          "name", "$1", "container", "(.+)") + f" and on (name) max by (name) (container_last_seen{{{SEL}}})", instant=True, fmt="table"),
], desc="Every container of the project. Click the container (or Opens) for its dashboard, lang for its runtime (Container dashboard, Runtime row). "
        "Labels come from docker-compose: container.type / lang / team / env.",
    # Fields read by the links (name, dash, lsvc, pj, lang) must stay in the data: hidden below, not excluded or renamed.
    hide=["Value #A", "image", "key", "k2", "appsvc", "container", PJ, SV] + [f"container_label_container_{l}" for l in L],
    rename={"Value #B": "Status", "Value #C": "Uptime", "Value #D": "CPU %", "Value #E": "Memory",
            "Value #F": "Restarts 24h", "Value #G": "Errors/min"},
    order=["name", "service", "type", "lang", "team", "env", "opens", "Value #B", "Value #C", "Value #D", "Value #E", "Value #F", "Value #G", "project"],
    sort=("CPU %", True),
    overrides=[named(col("name", links=[OPEN], width=230), "container"),
               named(col("opens", links=[OPEN], width=150), "Opens"), hidden("dash"),
               hidden("lsvc"), hidden("pj"), hidden("link_dash"), hidden("link_name"),
               col("service", width=130), col("type", width=100), col("team", width=100), col("env", width=80),
               col("lang", links=[RUNTIME], width=80),
               col("Status", width=80, cell={"type": "color-background", "mode": "basic"}, mappings=vmap({"0": ("DOWN", "red"), "1": ("UP", "green")})),
               col("Uptime", unit="s", decimals=0),
               col("CPU %", unit="percent", decimals=1, cell={"type": "gauge", "mode": "basic"}, th=steps((50, "orange"), (90, "red")), minv=0, maxv=100),
               col("Memory", unit="bytes"),
               col("Restarts 24h", decimals=0, th=steps((1, "orange"), (5, "red")), cell={"type": "color-text"}),
               col("Errors/min", decimals=1, th=steps((0.1, "orange"), (5, "red")), cell={"type": "color-text"})])
d.add(t, 24, 12)

d.row("Resources by container")
d.add(ts("CPU by container", [tgt(f"sum by (name) (rate(container_cpu_usage_seconds_total{{{SEL}}}[5m]))", "{{name}}")], desc="Cores.", stack=True), 12, 9)
d.add(ts("Memory by container", [tgt(f"sum by (name) (container_memory_working_set_bytes{{{SEL}}})", "{{name}}")], unit="bytes", stack=True), 12, 9)
d.add(ts("Network in by container", [tgt(f"sum by (name) (rate(container_network_receive_bytes_total{{{SEL}}}[5m]))", "{{name}}")], unit="Bps", stack=True), 12, 9)
d.add(ts("Network out by container", [tgt(f"sum by (name) (rate(container_network_transmit_bytes_total{{{SEL}}}[5m]))", "{{name}}")], unit="Bps", stack=True), 12, 9)
d.add(ts("Disk read by container", [tgt(f"sum by (name) (rate(container_fs_reads_bytes_total{{{SEL}}}[5m]))", "{{name}}")], unit="Bps", stack=True), 12, 9)
d.add(ts("Disk write by container", [tgt(f"sum by (name) (rate(container_fs_writes_bytes_total{{{SEL}}}[5m]))", "{{name}}")], unit="Bps", stack=True), 12, 9)

d.row("Logs")
d.add(ts("Error logs/min by container",
         [tgt('sum by (container) (rate(vector_log_lines_total{project=~"$project", level=~"error|fatal|panic"}[5m])) * 60', "{{container}}")],
         draw="bars", fill=70, stack=True), 12, 9)
d.add(ts("Log lines/min by level", [tgt('sum by (level) (rate(vector_log_lines_total{project=~"$project"}[5m])) * 60', "{{level}}")],
         stack=True, overrides=[{"matcher": {"id": "byName", "options": "error"}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}}]},
                                {"matcher": {"id": "byName", "options": "warn"}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "orange"}}]}]), 12, 9)
d.add(logs("Errors and warnings", 'project:~"$project" level:(error OR fatal OR panic OR warn) | sort by (_time desc) | limit 300'), 24, 12)

d.write("Infra/project.json")

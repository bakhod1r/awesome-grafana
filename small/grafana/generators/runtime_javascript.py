"""Runtime: JavaScript — containers labelled container.lang=javascript (React/Vue/... SPA served as static files).

A built JS bundle has no server runtime and no /metrics, so this page shows what can be seen without app
changes: the container (cAdvisor), nginx access lines turned into vector_frontend_* by Vector, and the logs.
Opened from the "Lang" column of the Docker projects dashboard: /d/runtime-javascript?var-container=<name>.
"""
from lib import *

L = 'container_label_container_lang="javascript"'
N = f'name=~"$container", name!="", {L}'                        # cAdvisor
F = 'container=~"$container", project=~"$project"'              # vector_frontend_* (access lines)
REQ = f'vector_frontend_http_requests_total{{{F}}}'
DUR = f'vector_frontend_http_request_duration_seconds_bucket{{{F}}}'
LQ = 'lang:=javascript container:~"^${container:raw}$"'

d = Dash("runtime-javascript", "Runtime: JavaScript",
         "JavaScript frontends (container.lang=javascript): static bundles served by nginx. No runtime metrics exist, "
         "so: container health, traffic from access logs, and logs.",
         ["runtime", "javascript", "frontend", "services"], time_from="now-3h",
         variables=[project_var(), container_var()])

d.row("Container")
d.add(stat("Running", f"count(time() - container_last_seen{{{N}}} < 60) or vector(0)", color_mode="value", graph=False,
           th=steps(base="blue"), desc="JavaScript containers seen by cAdvisor in the last minute."), 4, 4)
d.add(stat("Restarts (24h)", f"sum(resets(container_cpu_usage_seconds_total{{{N}}}[24h])) or vector(0)", graph=False,
           th=steps((1, "orange"), (5, "red"))), 4, 4)
d.add(stat("CPU (cores)", f"sum(rate(container_cpu_usage_seconds_total{{{N}}}[5m]))", decimals=3, color_mode="value", th=steps(base="blue")), 4, 4)
d.add(stat("Memory", f"sum(container_memory_working_set_bytes{{{N}}})", unit="bytes", color_mode="value", th=steps(base="blue")), 4, 4)
d.add(stat("Network out", f"sum(rate(container_network_transmit_bytes_total{{{N}}}[5m]))", unit="Bps", color_mode="value", th=steps(base="blue"),
           desc="Bytes sent: mostly the JS/CSS bundle and assets."), 4, 4)
d.add(stat("Uptime", f"min(time() - container_start_time_seconds{{{N}}})", unit="s", color_mode="value", graph=False, th=steps(base="blue")), 4, 4)
d.add(ts("CPU and memory", [tgt(f"sum by (name) (rate(container_cpu_usage_seconds_total{{{N}}}[5m]))", "{{name}} cpu cores"),
                            tgt(f"sum by (name) (container_memory_working_set_bytes{{{N}}})", "{{name}} memory")], fill=0,
         overrides=[{"matcher": {"id": "byRegexp", "options": ".*memory"}, "properties": [
             {"id": "unit", "value": "bytes"}, {"id": "custom.axisPlacement", "value": "right"}]}]), 12, 8)
d.add(ts("Network", [tgt(f"sum by (name) (rate(container_network_transmit_bytes_total{{{N}}}[5m]))", "{{name}} out"),
                     tgt(f"sum by (name) (rate(container_network_receive_bytes_total{{{N}}}[5m]))", "{{name}} in")], unit="Bps", fill=0), 12, 8)

d.row("Traffic (access logs)")
d.add(stat("Requests/s", f"sum(rate({REQ}[5m]))", unit="reqps", color_mode="value", th=steps(base="blue")), 6, 4)
d.add(stat("5xx %", f'sum(rate(vector_frontend_http_requests_total{{{F}, status_class="5xx"}}[5m])) / sum(rate({REQ}[5m])) * 100 or vector(0)',
           unit="percent", decimals=2, th=steps((1, "orange"), (5, "red"))), 6, 4)
d.add(stat("4xx %", f'sum(rate(vector_frontend_http_requests_total{{{F}, status_class="4xx"}}[5m])) / sum(rate({REQ}[5m])) * 100 or vector(0)',
           unit="percent", decimals=2, th=steps((5, "orange"), (20, "red")), desc="Mostly missing assets or bad links."), 6, 4)
d.add(stat("p95 latency", f"histogram_quantile(0.95, sum by (le) (rate({DUR}[5m])))", unit="s", decimals=3,
           th=steps((0.5, "orange"), (1, "red")), desc="Needs rt=$request_time in the nginx log format."), 6, 4)
for p in d.panels[-4:]:
    p["fieldConfig"]["defaults"]["noValue"] = "No access lines yet (nginx log to stdout)"
d.add(ts("Requests/s by status", [tgt(f"sum by (status_class) (rate({REQ}[5m]))", "{{status_class}}")], unit="reqps", stack=True), 12, 8)
d.add(ts("Latency p50 / p95", [tgt(f"histogram_quantile({q}, sum by (le) (rate({DUR}[5m])))", f"p{int(q * 100)}") for q in (0.5, 0.95)],
         unit="s", fill=0), 12, 8)

d.row("Logs")
d.add(logs("Errors and warnings", f"{LQ} level:(error OR warn) | sort by (_time desc) | limit 300"), 24, 10)
d.add(logs("All logs", f"{LQ} | sort by (_time desc) | limit 500"), 24, 10)
d.write("Apps/runtime-javascript.json")

"""Container: everything about one container, for any container (with or without labels or compose).

Opened when a container is clicked on the Project / Docker projects dashboards and its container.type has no
dedicated dashboard (or no label at all). cAdvisor for resources, Vector log metrics + VictoriaLogs for logs,
request logs (JSON with duration_ms / path / status) for API latency when the app writes them.
"""
from lib import *

UID, SLUG = "container", "container"
N = 'name="$container"'
LQ = 'container:="$container"'

d = Dash(UID, "Container",
         "One container: status, restarts, CPU, memory against its limit, network, disk, logs by level, top errors, "
         "and API latency from request logs when the app writes them.",
         ["docker", "container"], time_from="now-6h",
         variables=[{"name": "project", "label": "Project", "type": "textbox", "query": "", "hide": 2, "current": {"text": "", "value": ""}},
                    query_var("container", "Container", 'label_values(container_last_seen{name!=""}, name)', multi=False, include_all=False,
                              desc="Any running container on this Docker host.")])

d.row("Health")
d.add(stat("Status", f"max(time() - container_last_seen{{{N}}} < bool 60)", graph=False,
           mappings=vmap({"0": ("DOWN", "red"), "1": ("UP", "green")}), th=steps((1, "green"), base="red")), 3, 4)
d.add(stat("Uptime", f"max(time() - container_start_time_seconds{{{N}}})", unit="s", graph=False, color_mode="value", th=steps(base="blue")), 3, 4)
d.add(stat("Restarts (24h)", f"sum(resets(container_cpu_usage_seconds_total{{{N}}}[24h])) or vector(0)", graph=False, th=steps((1, "orange"), (5, "red"))), 3, 4)
d.add(stat("OOM kills (24h)", f"sum(increase(container_oom_events_total{{{N}}}[24h])) or vector(0)", graph=False, th=steps((1, "red"))), 3, 4)
d.add(stat("CPU %", f"sum(rate(container_cpu_usage_seconds_total{{{N}}}[5m])) * 100", unit="percent", decimals=1,
           th=steps((80, "orange"), (150, "red")), desc="100% = one full core."), 3, 4)
d.add(stat("Memory", f"sum(container_memory_working_set_bytes{{{N}}})", unit="bytes", color_mode="value", th=steps(base="blue")), 3, 4)
p = d.add(stat("Memory vs limit", f"sum(container_memory_working_set_bytes{{{N}}}) / sum(container_spec_memory_limit_bytes{{{N}}} > 0) * 100",
               unit="percent", decimals=0, th=steps((80, "orange"), (95, "red"))), 3, 4)
p["fieldConfig"]["defaults"]["noValue"] = "No memory limit set"
d.add(stat("Errors/min", f'sum(rate(vector_log_lines_total{{container="$container", level=~"error|fatal|panic"}}[5m])) * 60 or vector(0)',
           decimals=1, th=steps((0.1, "orange"), (5, "red"))), 3, 4)

d.row("Resources")
d.add(ts("CPU", [tgt(f"sum(rate(container_cpu_usage_seconds_total{{{N}}}[5m])) * 100", "cpu %"),
                 tgt(f"sum(rate(container_cpu_cfs_throttled_seconds_total{{{N}}}[5m])) * 100", "throttled %")], unit="percent", fill=10,
         desc="Throttled = the container wanted more CPU than its limit allows: requests get slower."), 12, 9)
d.add(ts("Memory", [tgt(f"sum(container_memory_working_set_bytes{{{N}}})", "working set"),
                    tgt(f"sum(container_memory_rss{{{N}}})", "rss"),
                    tgt(f"sum(container_memory_cache{{{N}}})", "cache"),
                    tgt(f"max(container_spec_memory_limit_bytes{{{N}}}) > 0", "limit")], unit="bytes", fill=0,
         desc="Working set = what counts against the limit (OOM kill at the limit). Cache can be dropped by the kernel."), 12, 9)
d.add(ts("Network", [tgt(f"sum(rate(container_network_receive_bytes_total{{{N}}}[5m]))", "in"),
                     tgt(f"sum(rate(container_network_transmit_bytes_total{{{N}}}[5m]))", "out")], unit="Bps", fill=10), 12, 9)
d.add(ts("Disk IO", [tgt(f"sum(rate(container_fs_reads_bytes_total{{{N}}}[5m]))", "read"),
                     tgt(f"sum(rate(container_fs_writes_bytes_total{{{N}}}[5m]))", "write")], unit="Bps", fill=10), 12, 9)
d.add(ts("Network errors and drops", [tgt(f"sum(rate(container_network_receive_errors_total{{{N}}}[5m])) + sum(rate(container_network_transmit_errors_total{{{N}}}[5m]))", "errors"),
                                      tgt(f"sum(rate(container_network_receive_packets_dropped_total{{{N}}}[5m])) + sum(rate(container_network_transmit_packets_dropped_total{{{N}}}[5m]))", "drops")],
         unit="pps", fill=0), 12, 9)
d.add(ts("Processes and open files", [tgt(f"sum(container_processes{{{N}}})", "processes"), tgt(f"sum(container_threads{{{N}}})", "threads"),
                                      tgt(f"sum(container_file_descriptors{{{N}}})", "open files")], fill=0), 12, 9)
d.panels[-1]["fieldConfig"]["defaults"]["noValue"] = "cAdvisor does not report processes on this host (needs --enable_metrics=process)"

d.row("Logs")
d.add(ts("Log lines/min by level", [tgt('sum by (level) (rate(vector_log_lines_total{container="$container"}[5m])) * 60', "{{level}}")], stack=True,
         overrides=[{"matcher": {"id": "byName", "options": "error"}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}}]},
                    {"matcher": {"id": "byName", "options": "warn"}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "orange"}}]}]), 12, 9)
d.add(vl_table("Top error messages", f'{LQ} level:(error OR fatal OR panic) | unpack_logfmt fields (msg, err, error) keep_original_fields | format if (msg:"") "<_msg>" as msg | stats by (msg, err, error) count() hits | sort by (hits desc) | limit 15',
               desc="Most frequent error lines.", sort=("hits", True)), 12, 9)
d.add(logs("Latest logs", f'{LQ} | sort by (_time desc) | limit 500'), 24, 12)

d.row("API requests (from request logs)", collapsed=True)
REQ = f'{LQ} duration_ms:*'
p = d.add(vl_table("Endpoints (slowest first)", f'{REQ} | stats by (method, path) count() requests, avg(duration_ms) avg_ms, '
                   f'quantile(0.95, duration_ms) p95_ms, max(duration_ms) max_ms | sort by (p95_ms desc) | limit 30',
                   desc="Needs JSON request logs with duration_ms, method, path, status. Empty for other apps.",
                   overrides=[col("p95_ms", unit="ms", th=steps((500, "orange"), (1000, "red")), cell={"type": "color-background", "mode": "basic"}),
                              col("max_ms", unit="ms"), col("avg_ms", unit="ms", decimals=1)]), 14, 10)
d.add(vl_table("Status codes", f'{REQ} | stats by (status) count() requests | sort by (requests desc)', sort=("requests", True)), 10, 10)
d.add(logs("Slow requests > 1s", f'{LQ} duration_ms:>1000 | sort by (duration_ms desc) | limit 100'), 24, 10)

d.write("Infra/container.json")

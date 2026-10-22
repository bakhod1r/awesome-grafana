"""Container: everything about one container, for any container (with or without labels or compose).

Opened when a container is clicked on the Project / Docker Projects dashboards and its container.type has no
dedicated dashboard (or no label at all). cAdvisor for resources, Vector log metrics + VictoriaLogs for logs,
HTTP metrics (Beyla or the app's /metrics) and the language runtime (heap, GC, event loop / goroutines / threads).
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
                              desc="Any running container on this Docker host."),
                    query_var("lang", "Language", 'label_values(container_last_seen{name="$container"}, container_label_container_lang)',
                              multi=False, include_all=False, hide=2, desc="container.lang label of the container: picks the Runtime row.")])

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

# HTTP traffic of the container. Backends: Beyla (eBPF) or the app's own /metrics (http_requests_total).
# Frontends (nginx serving a JS bundle): Vector turns their access log lines into vector_frontend_http_*.
H = 'job="apps", container="$container"'
F = 'container="$container"'
REQ = f"(sum(rate(http_requests_total{{{H}}}[5m])) or sum(rate(vector_frontend_http_requests_total{{{F}}}[5m])))"
def req(sel_b, sel_f):
    return f"(sum(rate(http_requests_total{{{H}, {sel_b}}}[5m])) or sum(rate(vector_frontend_http_requests_total{{{F}, {sel_f}}}[5m])))"
P95 = (f"(histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{{{H}}}[5m])))"
       f" or histogram_quantile(0.95, sum by (le) (rate(vector_frontend_http_request_duration_seconds_bucket{{{F}}}[5m]))))")
d.row("HTTP requests")
d.add(stat("Requests/s", REQ, unit="reqps", decimals=2, color_mode="value", th=steps(base="blue")), 6, 4)
d.add(stat("5xx %", f'{req('status=~"5.."', 'status_class="5xx"')} / {REQ} * 100', unit="percent", decimals=2, th=steps((1, "orange"), (5, "red"))), 6, 4)
d.add(stat("4xx %", f'{req('status=~"4.."', 'status_class="4xx"')} / {REQ} * 100', unit="percent", decimals=2, th=steps((5, "orange"), (20, "red"))), 6, 4)
d.add(stat("p95 latency", P95, unit="s", decimals=3, th=steps((0.5, "orange"), (1, "red")),
           desc="Frontends: needs rt=$request_time in the nginx log format."), 6, 4)
for p in d.panels[-4:]:
    p["fieldConfig"]["defaults"]["noValue"] = "No HTTP metrics"
d.add(table("Endpoints (slowest p95 first)", [
    tgt(f"sum by (route) (increase(http_requests_total{{{H}}}[$__range]))", instant=True, fmt="table"),
    tgt(f"histogram_quantile(0.95, sum by (route, le) (rate(http_request_duration_seconds_bucket{{{H}}}[$__range])))", instant=True, fmt="table")],
    desc="Backends: Beyla (beyla/beyla.yml) or the app's own /metrics. Frontends: see Web pages below.",
    rename={"Value #A": "requests", "Value #B": "p95"}, sort=("p95", True),
    overrides=[col("p95", unit="s", th=steps((0.5, "orange"), (1, "red")), cell={"type": "color-background", "mode": "basic"}, decimals=3),
               col("requests", decimals=0)]), 14, 10)
d.add(ts("Responses/s by status", [tgt(f"sum by (status) (rate(http_requests_total{{{H}}}[5m]))", "{{status}}"),
                                   tgt(f"sum by (status_class) (rate(vector_frontend_http_requests_total{{{F}}}[5m]))", "{{status_class}}")],
         unit="reqps", stack=True), 10, 10)

# Web pages: frontend access lines (nginx combined format) read straight from the logs.
EXTRACT = '| extract "<_> - <_> [<_>] \\"<method> <path> <_>\\" <status> <bytes> "'
FULL = '| extract "<_> - <_> [<_>] \\"<method> <path> <_>\\" <status> <bytes> \\"<referer>\\" \\"<agent>\\""'
BOT = 'agent:~"(?i)bot|crawl|spider|slurp|curl|wget|python|go-http|java/|okhttp|headless|monitor|blackbox|uptime"'
d.row("Web pages (frontend access logs)")
d.add(vl_table("Top pages", f'{LQ} {EXTRACT} | filter path:!"" | stats by (path) count() hits | sort by (hits desc) | limit 20', sort=("hits", True)), 8, 9)
d.add(vl_table("Top 404s", f'{LQ} {EXTRACT} | filter status:=404 | stats by (path) count() hits | sort by (hits desc) | limit 20',
               desc="Broken links and missing assets (.js / .css / images / fonts break the page).", sort=("hits", True)), 8, 9)
d.add(vl_table("Top referrers", f'{LQ} {FULL} | filter referer:!"-" referer:!"" | stats by (referer) count() hits | sort by (hits desc) | limit 15',
               sort=("hits", True)), 8, 9)
d.add(vl_ts("Humans vs bots (requests)", f'{LQ} {FULL} | format if ({BOT}) "bot" as kind | format if (!{BOT}) "human" as kind | stats by (kind) count()', "{{kind}}",
            desc="Bots = crawlers, scripts and monitors (blackbox probes count as bots)."), 12, 8)
d.add(vl_table("Clients that gave up (499)", f'{LQ} {EXTRACT} | filter status:=499 | stats by (path) count() hits | sort by (hits desc) | limit 20',
               desc="The browser closed the connection before the answer: the page was too slow.", sort=("hits", True)), 12, 8)
for p in d.panels[-5:]:
    p.setdefault("fieldConfig", {"defaults": {}, "overrides": []})["defaults"]["noValue"] = "No access lines"

# Language runtime of the container, picked by its container.lang label: each line only shows when the
# label matches (Node.js lines for lang=node, Go lines for lang=go, ...). Values from the app's own /metrics.
R = 'container="$container"'
def lang(expr, *langs):
    """expr, kept only when the container's container.lang is one of langs."""
    sel = "|".join(langs)
    return f'({expr}) and on() group(container_last_seen{{name="$container", container_label_container_lang=~"{sel}"}})'
d.row("Runtime ($lang)")
d.add(ts("Heap used", [tgt(lang(f"sum(nodejs_heap_size_used_bytes{{{R}}})", "node", "javascript", "typescript", "bun"), "heap"),
                       tgt(lang(f"sum(go_memstats_heap_inuse_bytes{{{R}}})", "go"), "heap"),
                       tgt(lang(f'sum(jvm_memory_used_bytes{{{R}, area="heap"}})', "java", "kotlin"), "heap"),
                       tgt(lang(f"sum(dotnet_total_memory_bytes{{{R}}})", "dotnet"), "managed memory"),
                       tgt(lang(f"sum(process_resident_memory_bytes{{{R}}})", "python", "php", "ruby", "rust"), "resident memory")],
         unit="bytes", fill=0), 8, 8)
d.add(ts("GC time (share of wall time)", [tgt(lang(f"sum(rate(nodejs_gc_duration_seconds_sum{{{R}}}[5m]))", "node", "javascript", "typescript", "bun"), "gc"),
                                          tgt(lang(f"sum(rate(go_gc_duration_seconds_sum{{{R}}}[5m]))", "go"), "gc"),
                                          tgt(lang(f"sum(rate(jvm_gc_pause_seconds_sum{{{R}}}[5m]))", "java", "kotlin"), "gc"),
                                          tgt(lang(f"sum(rate(python_gc_collections_total{{{R}}}[5m]))", "python"), "collections/s")],
         unit="percentunit", fill=0, desc="Time spent collecting garbage per second. Above 10% the app is starving for memory."), 8, 8)
d.add(ts("Concurrency", [tgt(lang(f"max(nodejs_eventloop_lag_p99_seconds{{{R}}})", "node", "javascript", "typescript", "bun"), "event loop lag p99 (s)"),
                         tgt(lang(f"sum(go_goroutines{{{R}}})", "go"), "goroutines"),
                         tgt(lang(f"sum(jvm_threads_live_threads{{{R}}})", "java", "kotlin"), "threads"),
                         tgt(lang(f"sum(dotnet_threadpool_num_threads{{{R}}})", "dotnet"), "thread pool")], fill=0,
         desc="Node.js: event loop lag above 100ms = the app is blocked. Go: goroutines growing forever = leak."), 8, 8)
for p in d.panels[-3:]:
    p["fieldConfig"]["defaults"]["noValue"] = "No runtime metrics for $lang (needs the app's /metrics)"

d.write("Infra/container.json")

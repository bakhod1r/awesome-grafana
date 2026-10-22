"""Frontend: what users get from a web-facing container (container.type=frontend).

Numbers come from access logs, no app change: Vector parses nginx-style lines of frontend containers
(stdout, vector_frontend_*) and of nginx log files (vector_nginx_*), plus
blackbox probes of URLs that contain the service name, LogsQL for pages and the container's cAdvisor numbers.
"""
from lib import *

UID, SLUG = "frontend", "frontend"
S = 'service=~"$service"'
REQ = f'{{__name__=~"vector_(frontend|nginx)_http_requests_total", {S}, project=~"$project"}}'
DUR = f'{{__name__=~"vector_(frontend|nginx)_http_request_duration_seconds_bucket", {S}, project=~"$project"}}'
LQ = 'service:~"^(${service:regex})$"'
def by_svc(expr):
    """cAdvisor series of the selected service: compose service, or the container name for docker-run containers
    (containers started with docker run have no compose label). label_match is MetricsQL (VictoriaMetrics datasource)."""
    e = f'label_replace(label_replace({expr}, "svc", "$1", "name", "(.+)"), "svc", "$1", "container_label_com_docker_compose_service", "(.+)")'
    return f'label_match({e}, "svc", "$service")'


# Access line: 1.2.3.4 - - [time] "GET /path HTTP/1.1" 200 612 "ref" "agent" rt=0.003
EXTRACT = '| extract "<_> - <_> [<_>] \\"<method> <path> <_>\\" <status> <bytes> "'

d = Dash(UID, "Frontend",
         "Frontend containers (label container.type=frontend) and nginx log files: traffic, errors, latency, pages and "
         "uptime, from access logs. Latency needs $request_time in the log line (rt=...).",
         ["frontend", "nginx", "services"], time_from="now-3h",
         variables=[project_var(),
                    query_var("service", "Service",
                              'label_values({__name__=~"vector_(frontend|nginx)_http_requests_total", project=~"$project"}, service)',
                              desc="Compose service of the frontend container, or the service label of an nginx log file.", all_value=None)])

d.row("Traffic")
d.add(stat("Requests/s", f"sum(rate({REQ}[5m]))", unit="reqps", color_mode="value", th=steps(base="blue")), 4, 4)
d.add(stat("5xx %", f"sum(rate({REQ[:-1]}, status_class=\"5xx\"}}[5m])) / sum(rate({REQ}[5m])) * 100 or vector(0)", unit="percent", decimals=2,
           th=steps((1, "orange"), (5, "red")), desc="Server errors: users saw a broken page or failed call."), 4, 4)
d.add(stat("4xx %", f"sum(rate({REQ[:-1]}, status_class=\"4xx\"}}[5m])) / sum(rate({REQ}[5m])) * 100 or vector(0)", unit="percent", decimals=2,
           th=steps((5, "orange"), (20, "red")), desc="Missing pages, bad links, blocked requests."), 4, 4)
d.add(stat("p95 latency", f"histogram_quantile(0.95, sum by (le) (rate({DUR}[5m])))", unit="s", decimals=3,
           th=steps((0.5, "orange"), (1, "red")), desc="Server time per request (rt=). Empty when the log format has no rt."), 4, 4)
d.add(stat("Uptime (probe, 24h)", f'avg_over_time(probe_success{{instance=~".*$service.*"}}[24h]) * 100', unit="percent", decimals=2,
           th=steps((99, "orange"), (99.9, "green"), base="red"), desc="Blackbox probes of URLs containing the service name (prometheus/sites.yml)."), 4, 4)
d.add(stat("SSL expires in", f'min(probe_ssl_earliest_cert_expiry{{instance=~".*$service.*"}} - time())', unit="s", decimals=0,
           th=steps((7 * 86400, "orange"), (21 * 86400, "green"), base="red"), desc="Empty for plain http."), 4, 4)

d.add(ts("Requests/s by status", [tgt(f"sum by (status_class) (rate({REQ}[5m]))", "{{status_class}}")], unit="reqps", stack=True,
         overrides=[{"matcher": {"id": "byName", "options": "5xx"}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}}]},
                    {"matcher": {"id": "byName", "options": "4xx"}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "orange"}}]},
                    {"matcher": {"id": "byName", "options": "2xx"}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "green"}}]}]), 12, 8)
d.add(ts("Latency p50 / p95 / p99", [tgt(f"histogram_quantile({q}, sum by (le) (rate({DUR}[5m])))", f"p{int(q * 100)}") for q in (0.5, 0.95, 0.99)],
         unit="s", fill=0), 12, 8)
d.add(ts("Requests/s by method", [tgt(f"sum by (method) (rate({REQ}[5m]))", "{{method}}")], unit="reqps", stack=True), 12, 8)
d.add(ts("Probe response time", [tgt(f'probe_duration_seconds{{instance=~".*$service.*"}}', "{{instance}}")], unit="s", fill=0,
         desc="Full request time as an outside client sees it (blackbox)."), 12, 8)

d.row("Pages")
d.add(vl_table("Top pages", f'{LQ} {EXTRACT} | filter path:!"" | stats by (path) count() hits | sort by (hits desc) | limit 20', desc="Most requested paths in the selected range.", sort=("hits", True)), 8, 10)
d.add(vl_table("Top 404s", f'{LQ} {EXTRACT} | filter status:=404 | stats by (path) count() hits | sort by (hits desc) | limit 20', desc="Broken links and missing assets.", sort=("hits", True)), 8, 10)
d.add(vl_table("Top 5xx pages", f'{LQ} {EXTRACT} | filter status:~"5.." | stats by (path, status) count() hits | sort by (hits desc) | limit 20', desc="Pages that failed on the server.", sort=("hits", True)), 8, 10)
d.add(logs("Errors (4xx / 5xx, error log)", f'{LQ} level:(error OR warn) | sort by (_time desc) | limit 300'), 24, 10)

d.row("Visitors")
FULL = '| extract "<_> - <_> [<_>] \\"<method> <path> <_>\\" <status> <bytes> \\"<referer>\\" \\"<agent>\\""'
BOT = 'agent:~"(?i)bot|crawl|spider|slurp|curl|wget|python|go-http|java/|okhttp|headless|monitor|blackbox|uptime"'
d.add(vl_ts("Humans vs bots (requests)", f'{LQ} {FULL} | format if ({BOT}) "bot" as kind | format if (!{BOT}) "human" as kind | stats by (kind) count()', "{{kind}}",
            desc="Bots = user agents of crawlers, scripts and monitors (blackbox probes count as bots)."), 12, 9)
d.add(vl_table("Top referrers", f'{LQ} {FULL} | filter referer:!"-" referer:!"" | stats by (referer) count() hits | sort by (hits desc) | limit 15',
               desc="Where visitors come from (other sites, search engines, your own pages).", sort=("hits", True)), 12, 9)
d.add(vl_table("Broken assets (404 on .js / .css / images / fonts)",
               f'{LQ} {EXTRACT} | filter status:=404 path:~"\\\\.(js|css|png|jpe?g|svg|webp|ico|woff2?)" | stats by (path) count() hits | sort by (hits desc) | limit 20',
               desc="A missing bundle or font breaks the page for every visitor.", sort=("hits", True)), 12, 9)
d.add(vl_table("Clients that gave up (499) and slow pages",
               f'{LQ} {EXTRACT} | filter status:=499 | stats by (path) count() hits | sort by (hits desc) | limit 20',
               desc="499 = the browser closed the connection before the answer came: the page was too slow.", sort=("hits", True)), 12, 9)
d.add(ts("Bytes served/s", [tgt("sum(" + by_svc('rate(container_network_transmit_bytes_total{name!=""}[5m])') + ")", "sent")],
         unit="Bps", desc="Traffic sent to browsers (container network out)."), 24, 7)

d.row("Container")
d.add(ts("CPU", [tgt("sum by (name) (" + by_svc('rate(container_cpu_usage_seconds_total{name!=""}[5m])') + ")", "{{name}}")],
         unit="short", desc="Cores."), 12, 8)
d.add(ts("Memory", [tgt("sum by (name) (" + by_svc('container_memory_working_set_bytes{name!=""}') + ")", "{{name}}")],
         unit="bytes"), 12, 8)

d.write("Apps/frontend.json")

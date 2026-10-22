"""Proxy: reverse proxies / load balancers (container.type=proxy). Traefik (built-in /metrics, job traefik),
Caddy (built-in caddy_http_*), HAProxy (built-in haproxy_*), nginx (stub_status exporter + access-log metrics).
The main question: is a slow or failing request the proxy's fault or the upstream's?"""
from lib import *

UID, SLUG = "proxy", "proxy"
T = 'instance=~"$instance"'
NO_T = "No Traefik scraped (prometheus/exporters/traefik.yml)"

d = Dash(UID, "Proxy",
         "Reverse proxies: traffic per route and upstream, 502/503/504 (upstream down or slow), latency, open connections. "
         "Traefik, Caddy, HAProxy and nginx. Opened for containers labelled container.type=proxy.",
         ["proxy", "traefik", "nginx", "services"], time_from="now-3h",
         variables=[project_var(), container_var(),
                    query_var("instance", "Traefik", 'label_values(traefik_config_reloads_total{project=~"$project"}, instance)', desc="Traefik instance."),
                    query_var("service", "Upstream", 'label_values(traefik_service_requests_total{instance=~"$instance"}, service)',
                              desc="Traefik service = the upstream (backend) behind a route.")])

health_row(d, "proxy")


def empty(p, note):
    p["fieldConfig"]["defaults"]["noValue"] = note
    return p


S = f'{T}, service=~"$service"'
d.row("Traefik — traffic")
d.add(stat("Requests/s", f"sum(rate(traefik_entrypoint_requests_total{{{T}}}[5m]))", unit="reqps", color_mode="value", th=steps(base="blue")), 4, 4)
d.add(stat("5xx %", f"sum(rate(traefik_service_requests_total{{{S}, code=~\"5..\"}}[5m])) / sum(rate(traefik_service_requests_total{{{S}}}[5m])) * 100 or vector(0)",
           unit="percent", decimals=2, th=steps((1, "orange"), (5, "red"))), 4, 4)
d.add(stat("502/503/504 (1h)", f"sum(increase(traefik_service_requests_total{{{S}, code=~\"502|503|504\"}}[1h])) or vector(0)", decimals=0,
           th=steps((1, "orange"), (50, "red")), graph=False, desc="Bad gateway / unavailable / gateway timeout: the upstream is down, refusing or too slow."), 4, 4)
d.add(stat("p95 latency", f"histogram_quantile(0.95, sum by (le) (rate(traefik_service_request_duration_seconds_bucket{{{S}}}[5m])))", unit="s", decimals=3,
           th=steps((0.5, "orange"), (1, "red"))), 4, 4)
d.add(stat("Open connections", f"sum(traefik_open_connections{{{T}}})", color_mode="value", th=steps(base="blue")), 4, 4)
d.add(stat("Config reload", f"max(traefik_config_last_reload_success{{{T}}}) >= bool max(traefik_config_last_reload_failure{{{T}}} or vector(0))", mappings=vmap({"0": ("FAILED", "red"), "1": ("OK", "green")}), graph=False,
           th=steps((1, "green"), base="red"), desc="Last dynamic-config reload. FAILED = new routes did not apply."), 4, 4)

d.add(empty(ts("Requests/s by status code", [tgt(f"sum by (code) (rate(traefik_service_requests_total{{{S}}}[5m]))", "{{code}}")], unit="reqps", stack=True,
               overrides=[{"matcher": {"id": "byRegexp", "options": "5.."}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}}]},
                          {"matcher": {"id": "byRegexp", "options": "4.."}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "orange"}}]}]), NO_T), 12, 9)
d.add(empty(ts("Latency p50 / p95 / p99", [tgt(f"histogram_quantile({q}, sum by (le) (rate(traefik_service_request_duration_seconds_bucket{{{S}}}[5m])))", f"p{int(q * 100)}")
                                           for q in (0.5, 0.95, 0.99)], unit="s", fill=0,
               desc="Time Traefik waits for the upstream plus its own work: high here = slow backend."), NO_T), 12, 9)
d.add(empty(ts("Requests/s by upstream", [tgt(f"sum by (service) (rate(traefik_service_requests_total{{{S}}}[5m]))", "{{service}}")], unit="reqps", stack=True), NO_T), 12, 9)
d.add(empty(ts("p95 by upstream", [tgt(f"histogram_quantile(0.95, sum by (service, le) (rate(traefik_service_request_duration_seconds_bucket{{{S}}}[5m])))", "{{service}}")],
               unit="s", fill=0), NO_T), 12, 9)
d.add(empty(ts("Requests/s by router", [tgt(f"sum by (router) (rate(traefik_router_requests_total{{{T}}}[5m]))", "{{router}}")], unit="reqps", stack=True,
               desc="Router = a rule (host / path) in the Traefik config."), NO_T), 12, 9)
d.add(empty(ts("Traffic", [tgt(f"sum(rate(traefik_entrypoint_requests_bytes_total{{{T}}}[5m]))", "in (requests)"),
                           tgt(f"sum(rate(traefik_entrypoint_responses_bytes_total{{{T}}}[5m]))", "out (responses)")], unit="Bps", fill=0), NO_T), 12, 9)
d.add(table("Upstreams (selected range)", [
    tgt(f"sum by (service) (increase(traefik_service_requests_total{{{S}}}[$__range]))", instant=True, fmt="table"),
    tgt(f"sum by (service) (increase(traefik_service_requests_total{{{S}, code=~\"4..\"}}[$__range])) or sum by (service) (increase(traefik_service_requests_total{{{S}}}[$__range])) * 0", instant=True, fmt="table"),
    tgt(f"sum by (service) (increase(traefik_service_requests_total{{{S}, code=~\"5..\"}}[$__range])) or sum by (service) (increase(traefik_service_requests_total{{{S}}}[$__range])) * 0", instant=True, fmt="table"),
    tgt(f"histogram_quantile(0.95, sum by (service, le) (rate(traefik_service_request_duration_seconds_bucket{{{S}}}[$__range])))", instant=True, fmt="table"),
], desc="Each upstream behind the proxy: how many requests, how many failed, how slow.",
    rename={"service": "Upstream", "Value #A": "Requests", "Value #B": "4xx", "Value #C": "5xx", "Value #D": "p95"}, sort=("p95", True),
    overrides=[col("Requests", decimals=0), col("4xx", decimals=0), col("5xx", decimals=0, th=steps((1, "red")), cell={"type": "color-text"}),
               col("p95", unit="s", decimals=3, th=steps((0.5, "orange"), (1, "red")), cell={"type": "color-background", "mode": "basic"})]), 24, 8)

d.row("Caddy / HAProxy / nginx", collapsed=True)
d.add(empty(ts("Caddy requests/s by code", [tgt('sum by (code) (rate(caddy_http_requests_total{project=~"$project"}[5m]))', "{{code}}")], unit="reqps", stack=True),
            "No Caddy metrics (enable the metrics directive)"), 12, 8)
d.add(empty(ts("Caddy p95", [tgt('histogram_quantile(0.95, sum by (le) (rate(caddy_http_request_duration_seconds_bucket{project=~"$project"}[5m])))', "p95")], unit="s", fill=0),
            "No Caddy metrics (enable the metrics directive)"), 12, 8)
d.add(empty(ts("HAProxy responses/s by code (backends)", [tgt('sum by (code) (rate(haproxy_backend_http_responses_total{project=~"$project"}[5m]))', "{{code}}")], unit="reqps", stack=True),
            "No HAProxy metrics (prometheus-exporter in a frontend)"), 12, 8)
d.add(empty(ts("HAProxy backends up", [tgt('sum by (proxy) (haproxy_backend_active_servers{project=~"$project"})', "{{proxy}}")]),
            "No HAProxy metrics (prometheus-exporter in a frontend)"), 12, 8)
d.add(empty(ts("nginx connections (stub_status)", [tgt('sum(nginx_connections_active)', "active"), tgt('sum(nginx_connections_waiting)', "waiting")]),
            "No nginx-prometheus-exporter (profile nginx)"), 12, 8)
d.add(empty(ts("nginx requests/s by status (access logs)", [tgt('sum by (status_class) (rate(vector_nginx_http_requests_total[5m]))', "{{status_class}}")],
               unit="reqps", stack=True), "No nginx access-log metrics"), 12, 8)

d.row("Logs")
d.add(logs("Errors and warnings", f'{type_logs("proxy")} level:(error OR fatal OR panic OR warn) | sort by (_time desc) | limit 300'), 24, 10)

d.write("Apps/proxy.json")

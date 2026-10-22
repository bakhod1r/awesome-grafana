"""App SLO: per service availability (non-5xx) and latency (<= 1s) objectives, error budget and burn rate for job "apps".
Ratios come from the app-slo-recording rules (prometheus/rules/recording.yml); the burn-rate alerts are the app-slo group
in prometheus/rules/alerts.yml. Change an objective in both places: AVAIL/LAT below and the 0.005 / 0.01 in the rules."""
from lib import *

UID, SLUG = "app-slo", "app-slo"
AVAIL, LAT = 99.5, 99.0  # objectives, percent
AB, LB = round(1 - AVAIL / 100, 6), round(1 - LAT / 100, 6)  # budgets as ratios
S = 'service=~"$service"'
R30 = "30d"

ERR30 = f'sum by (service) (increase(http_requests_total{{job="apps", {S}, status=~"5.."}}[{R30}])) / sum by (service) (increase(http_requests_total{{job="apps", {S}}}[{R30}]))'
SLOW30 = (f'1 - sum by (service) (increase(http_request_duration_seconds_bucket{{job="apps", {S}, le="1"}}[{R30}])) '
          f'/ sum by (service) (increase(http_request_duration_seconds_count{{job="apps", {S}}}[{R30}]))')
BURN_TH = steps((1, "yellow"), (6, "orange"), (14.4, "red"))
BUDGET_TH = steps((25, "orange"), (50, "green"), base="red")
SVC_LINKS = [{"title": "Only this service", "url": f"/d/{UID}/{SLUG}?${{__url_time_range}}&var-service=${{__data.fields.service}}"},
             {"title": "Endpoints of this service", "url": "/d/endpoints/app-endpoints?${__url_time_range}&var-service=${__data.fields.service}"}]


def burn_overrides():
    return [{"matcher": {"id": "byRegexp", "options": ".*"}, "properties": [{"id": "custom.thresholdsStyle", "value": {"mode": "line+area"}}]}]


d = Dash(UID, "App SLO",
         f"Service level objectives for your apps (job apps): availability {AVAIL}% of requests are not 5xx, latency {LAT}% of requests finish within 1s, "
         "over a rolling 30 days. Error budget = how many bad requests are still allowed; burn rate = how fast it is being used "
         "(1x = exactly used up in 30 days). Alerts: AppErrorBudget*/AppLatencyBudget* (fast burn 14.4x critical, slow burn 6x warning).",
         ["slo", "apps", "error-budget", "burn-rate", "endpoints"], time_from="now-24h",
         variables=[query_var("service", "Service", "label_values(service:app_requests:rate5m, service)", desc="Services of job apps with traffic.")],
         links=[{"title": "Probes & SLO (blackbox)", "type": "link", "icon": "dashboard", "url": "/d/probes-slo/probes-slo?${__url_time_range}", "targetBlank": False}])

d.row("All services — 30 days")
d.add(text(f"**Availability SLO {AVAIL}%** → budget {AB * 100:g}% of requests may fail (5xx). **Latency SLO {LAT}%** → budget {LB * 100:g}% may take over 1s.  \n"
           "**Budget left** 100% = untouched, 0% = used up (stop risky deploys, fix reliability first). **Burn 1h** above 14.4x pages, above 6x over 6h warns. "
           "Click a service name to filter, or jump to its endpoints."), 24, 2)
tb = table("SLO per service", [
    tgt(f"(1 - ({ERR30})) * 100", instant=True, fmt="table"),
    tgt(f"(1 - ({ERR30}) / {AB}) * 100", instant=True, fmt="table"),
    tgt(f"service:app_request_errors:ratio_rate1h{{{S}}} / {AB}", instant=True, fmt="table"),
    tgt(f"(1 - ({SLOW30})) * 100", instant=True, fmt="table"),
    tgt(f"(1 - ({SLOW30}) / {LB}) * 100", instant=True, fmt="table"),
    tgt(f"service:app_request_slow:ratio_rate1h{{{S}}} / {LB}", instant=True, fmt="table"),
    tgt(f"service:app_requests:rate5m{{{S}}}", instant=True, fmt="table"),
], rename={"Value #A": "Availability 30d", "Value #B": "Error budget left", "Value #C": "Error burn 1h",
           "Value #D": "Within 1s 30d", "Value #E": "Latency budget left", "Value #F": "Latency burn 1h", "Value #G": "Req/s"},
    order=["service", "Availability 30d", "Error budget left", "Error burn 1h", "Within 1s 30d", "Latency budget left", "Latency burn 1h", "Req/s"],
    sort=("Error budget left", False),
    overrides=[col("service", links=SVC_LINKS, width=200),
               col("Availability 30d", unit="percent", decimals=3), col("Within 1s 30d", unit="percent", decimals=3),
               col(".*budget left", unit="percent", decimals=1, minv=0, maxv=100, th=BUDGET_TH, regex=True,
                   cell={"type": "gauge", "mode": "basic", "valueDisplayMode": "text"}),
               col(".*burn 1h", unit="x", decimals=1, th=BURN_TH, cell=TXT, regex=True),
               col("Req/s", unit="reqps", decimals=2)])
tb["fieldConfig"]["defaults"]["noValue"] = "No app traffic: job apps has no http_requests_total yet."
d.add(tb, 24, 9)

d.row("Availability (non-5xx)")
d.add(stat("Availability 30d", f"min((1 - ({ERR30})) * 100)", unit="percent", decimals=3, th=steps((AVAIL, "green"), base="red"), graph=False,
           desc="Worst selected service. Raw counters over 30 days (VictoriaMetrics)."), 6, 5)
d.add(stat("Error budget left", f"min((1 - ({ERR30}) / {AB}) * 100)", unit="percent", decimals=1, th=BUDGET_TH, graph=False,
           desc="Worst selected service. Negative = objective already missed this month."), 6, 5)
d.add(stat("Error burn 1h", f"max(service:app_request_errors:ratio_rate1h{{{S}}}) / {AB}", unit="x", decimals=1, th=BURN_TH, graph=False), 6, 5)
d.add(stat("Error burn 6h", f"max(service:app_request_errors:ratio_rate6h{{{S}}}) / {AB}", unit="x", decimals=1, th=BURN_TH, graph=False), 6, 5)
d.add(ts("Error burn rate", [tgt(f"service:app_request_errors:ratio_rate1h{{{S}}} / {AB}", "{{service}} 1h"),
                             tgt(f"service:app_request_errors:ratio_rate6h{{{S}}} / {AB}", "{{service}} 6h")], unit="x", fill=0, th=BURN_TH, minv=0,
         desc="1x = budget lasts exactly 30 days. Fast-burn alert: 1h and 5m above 14.4x. Slow-burn: 6h and 30m above 6x."), 12, 8)
d.add(ts("5xx share", [tgt(f"service:app_request_errors:ratio_rate5m{{{S}}} * 100", "{{service}}")], unit="percent", fill=0,
         th=steps((AB * 100, "red")), minv=0, desc=f"Dashed line = budget ({AB * 100:g}%). Spending above it eats the budget."), 12, 8)

d.row("Latency (within 1s)")
d.add(stat("Within 1s 30d", f"min((1 - ({SLOW30})) * 100)", unit="percent", decimals=3, th=steps((LAT, "green"), base="red"), graph=False), 6, 5)
d.add(stat("Latency budget left", f"min((1 - ({SLOW30}) / {LB}) * 100)", unit="percent", decimals=1, th=BUDGET_TH, graph=False), 6, 5)
d.add(stat("Latency burn 1h", f"max(service:app_request_slow:ratio_rate1h{{{S}}}) / {LB}", unit="x", decimals=1, th=BURN_TH, graph=False), 6, 5)
d.add(stat("Latency burn 6h", f"max(service:app_request_slow:ratio_rate6h{{{S}}}) / {LB}", unit="x", decimals=1, th=BURN_TH, graph=False), 6, 5)
d.add(ts("Latency burn rate", [tgt(f"service:app_request_slow:ratio_rate1h{{{S}}} / {LB}", "{{service}} 1h"),
                               tgt(f"service:app_request_slow:ratio_rate6h{{{S}}} / {LB}", "{{service}} 6h")], unit="x", fill=0, th=BURN_TH, minv=0), 12, 8)
d.add(ts("Share slower than 1s", [tgt(f"service:app_request_slow:ratio_rate5m{{{S}}} * 100", "{{service}}")], unit="percent", fill=0,
         th=steps((LB * 100, "red")), minv=0, desc="Needs http_request_duration_seconds with a le=\"1\" bucket (Prometheus client defaults have it)."), 12, 8)

d.row("Traffic")
d.add(ts("Requests/s", [tgt(f"service:app_requests:rate5m{{{S}}}", "{{service}}")], unit="reqps", stack=True,
         desc="Below 0.05 req/s the burn-rate alerts stay quiet: a single failure on an idle service is not an outage."), 24, 7)

d.write("Observability/app-slo.json")

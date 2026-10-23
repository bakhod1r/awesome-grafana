"""SRE overview: are the apps healthy for their users, how much error budget is left, how often things break
and how fast they are fixed, and what changed. Built only from data the stack already has:
Beyla HTTP metrics (job "apps"), the app-slo recording rules, Prometheus ALERTS and cAdvisor."""
from lib import *

UID, SLUG = "sre", "sre"
S = 'service=~"$service"'
APPS = f'job="apps", {S}'

# App SLO objectives, same as the app-slo rules in prometheus/rules/alerts.yml
ERR_BUDGET, SLOW_BUDGET = 0.005, 0.01
EVAL = 15  # Prometheus evaluation_interval (s): one ALERTS sample per evaluation while an alert fires

d = Dash(UID, "SRE", "SRE overview: golden signals per service, 30-day SLO and error budget, incidents with MTTR, "
         "deploys and restarts. Objectives: 99.5% of requests not 5xx, 99% within 1s.",
         ["sre", "slo", "observability"], time_from="now-7d", refresh="1m",
         variables=[query_var("service", "Service", 'label_values(service:app_requests:rate5m, service)',
                              desc="Service name from Beyla (beyla/beyla.yml) or the app's own /metrics.")])

d.row("How to read")
d.add(text("**Golden signals**: traffic, errors, latency and saturation for each service right now. "
           "**SLO**: share of good requests over 30 days and how much of the error budget is left "
           "(100% = untouched, 0% = objective missed). **Incidents**: alerts in the selected range, how long they "
           "lasted on average (MTTR). **Changes**: deploys and restarts, the usual cause of incidents."), 24, 3)

d.row("Golden signals — per service, now")
d.add(table("Services", [
    tgt(f'sum by (service) (service:app_requests:rate5m{{{S}}})', instant=True, fmt="table"),
    tgt(f'sum by (service) (service:app_request_errors:ratio_rate5m{{{S}}})', instant=True, fmt="table"),
    tgt(f'histogram_quantile(0.95, sum by (le, service) (rate(http_request_duration_seconds_bucket{{{APPS}}}[5m])))', instant=True, fmt="table"),
    tgt(f'sum by (service) (service:app_request_slow:ratio_rate5m{{{S}}})', instant=True, fmt="table"),
    tgt(f'label_replace(sum by (name) (rate(container_cpu_usage_seconds_total{{name=~"$service"}}[5m])), "service", "$1", "name", "(.+)")',
        instant=True, fmt="table"),
], desc="Traffic (requests/s), errors (share of 5xx), latency (p95 and share over 1s) and saturation (CPU cores of the "
        "container with the same name, when there is one).",
    rename={"Value #A": "Req/s", "Value #B": "5xx %", "Value #C": "p95", "Value #D": "Over 1s %", "Value #E": "CPU"},
    hide=("name",), order=["service", "Req/s", "5xx %", "p95", "Over 1s %", "CPU"], sort=("Req/s", True),
    overrides=[col("Req/s", unit="reqps", decimals=2),
               col("5xx %", unit="percentunit", cell=TXT, th=steps((0.005, "yellow"), (0.02, "red")), decimals=2),
               col("p95", unit="s", cell=TXT, th=steps((0.5, "yellow"), (1, "red"))),
               col("Over 1s %", unit="percentunit", cell=TXT, th=steps((0.01, "yellow"), (0.05, "red")), decimals=2),
               col("CPU", unit="short", decimals=2),
               col("service", links=[goto("endpoints", "endpoints", "Endpoints of ${__value.raw}", "&var-service=${__value.raw}")])]), 24, 8)
d.add(ts("Traffic", [tgt(f'sum by (service) (service:app_requests:rate5m{{{S}}})', "{{service}}")], unit="reqps"), 8, 8)
d.add(ts("Errors (5xx share)", [tgt(f'sum by (service) (service:app_request_errors:ratio_rate5m{{{S}}})', "{{service}}")],
         unit="percentunit", th=steps((ERR_BUDGET, "red")), fill=0), 8, 8)
d.add(ts("Latency p95", [tgt(f'histogram_quantile(0.95, sum by (le, service) (rate(http_request_duration_seconds_bucket{{{APPS}}}[5m])))',
                            "{{service}}")], unit="s", th=steps((1, "red")), fill=0), 8, 8)

d.row("SLO and error budget — last 30 days")
avail = f'1 - avg_over_time(service:app_request_errors:ratio_rate5m{{{S}}}[30d])'
fast = f'1 - avg_over_time(service:app_request_slow:ratio_rate5m{{{S}}}[30d])'
d.add(table("SLO by service", [
    tgt(f'sum by (service) ({avail})', instant=True, fmt="table"),
    tgt(f'sum by (service) (1 - avg_over_time(service:app_request_errors:ratio_rate5m{{{S}}}[30d]) / {ERR_BUDGET})', instant=True, fmt="table"),
    tgt(f'sum by (service) (service:app_request_errors:ratio_rate1h{{{S}}}) / {ERR_BUDGET}', instant=True, fmt="table"),
    tgt(f'sum by (service) ({fast})', instant=True, fmt="table"),
    tgt(f'sum by (service) (1 - avg_over_time(service:app_request_slow:ratio_rate5m{{{S}}}[30d]) / {SLOW_BUDGET})', instant=True, fmt="table"),
], desc="Availability = share of requests without 5xx (objective 99.5%). Fast = share within 1s (objective 99%). "
        "Budget left: 100% untouched, 0% objective missed. Burn 1h: 1 = spending the budget exactly on schedule, "
        "14 = the month's budget gone in about 2 days. Averages of 5-minute ratios, so idle hours weigh as much as busy ones.",
    rename={"Value #A": "Availability 30d", "Value #B": "Error budget left", "Value #C": "Burn 1h",
            "Value #D": "Fast (<1s) 30d", "Value #E": "Latency budget left"},
    order=["service", "Availability 30d", "Error budget left", "Burn 1h", "Fast (<1s) 30d", "Latency budget left"],
    sort=("Error budget left", False),
    overrides=[col("Availability 30d", unit="percentunit", decimals=3, cell=TXT, th=steps((0.995, "green"), base="red")),
               col("Fast (<1s) 30d", unit="percentunit", decimals=3, cell=TXT, th=steps((0.99, "green"), base="red")),
               col("Error budget left", unit="percentunit", cell=BAR, th=steps((0.25, "yellow"), (0.5, "green"), base="red"), minv=0, maxv=1),
               col("Latency budget left", unit="percentunit", cell=BAR, th=steps((0.25, "yellow"), (0.5, "green"), base="red"), minv=0, maxv=1),
               col("Burn 1h", decimals=1, cell=TXT, th=steps((1, "yellow"), (6, "orange"), (14.4, "red")))]), 24, 8)
d.add(ts("Error budget left over time", [tgt(f'sum by (service) (1 - avg_over_time(service:app_request_errors:ratio_rate5m{{{S}}}[30d]) / {ERR_BUDGET})',
                                            "{{service}}")], unit="percentunit", th=steps((0.25, "red")), maxv=1, fill=0,
         desc="Rolling 30-day budget. A steady slope down = errors all the time; a cliff = one incident."), 12, 8)
d.add(ts("Burn rate (1h)", [tgt(f'sum by (service) (service:app_request_errors:ratio_rate1h{{{S}}}) / {ERR_BUDGET}', "{{service}}")],
         th=steps((1, "yellow"), (14.4, "red")), fill=0,
         desc="How fast the error budget is spent. Above 14.4 for an hour pages (AppErrorBudgetFastBurn)."), 12, 8)

d.row("Incidents — selected time range")
crit = 'ALERTS_FOR_STATE{severity="critical"}'
episodes = lambda sel: f'(sum(changes({sel}[$__range])) + count(count_over_time({sel}[$__range]))) or vector(0)'
firing = lambda sev: f'(sum(count_over_time(ALERTS{{alertstate="firing", severity="{sev}"}}[$__range])) * {EVAL}) or vector(0)'
d.add(stat("Critical incidents", episodes(crit), th=steps((1, "yellow"), (5, "red")), graph=False,
           desc="Critical alert episodes that started in the range (a re-fire of the same alert counts again)."), 4, 4)
d.add(stat("Warning incidents", episodes('ALERTS_FOR_STATE{severity="warning"}'), th=steps((10, "yellow")), graph=False), 4, 4)
d.add(stat("Firing now", 'count(ALERTS{alertstate="firing", alertname!="Watchdog"}) or vector(0)',
           th=steps((1, "red")), graph=False), 4, 4)
d.add(stat("Time in critical", firing("critical"), unit="s", th=steps((3600, "yellow"), (6 * 3600, "red")), graph=False,
           desc="Sum of how long each critical alert was firing."), 4, 4)
d.add(stat("MTTR (critical)", f'({firing("critical")}) / ({episodes(crit)} > 0)', unit="s",
           th=steps((900, "yellow"), (3600, "red")), graph=False,
           desc="Mean time to recover: time in critical / critical incidents. Approximate (15s resolution)."), 4, 4)
d.add(stat("Availability (probes)", 'avg(avg_over_time(probe_success[$__range]))', unit="percentunit", decimals=3,
           th=steps((0.999, "green"), base="red"), graph=False, desc="Websites and ports probed by blackbox, whole range."), 4, 4)
d.add(table("Alerts in range", [
    tgt('sum by (alertname, severity) (changes(ALERTS_FOR_STATE[$__range]) + 1)', instant=True, fmt="table"),
    tgt(f'sum by (alertname, severity) (count_over_time(ALERTS{{alertstate="firing"}}[$__range])) * {EVAL}', instant=True, fmt="table"),
    tgt(f'sum by (alertname, severity) (count_over_time(ALERTS{{alertstate="firing"}}[$__range])) * {EVAL}'
        ' / sum by (alertname, severity) (changes(ALERTS_FOR_STATE[$__range]) + 1)', instant=True, fmt="table"),
], desc="Every alert that fired in the range: how often, total firing time, and average duration of one episode.",
    rename={"Value #A": "Episodes", "Value #B": "Firing time", "Value #C": "Avg duration"},
    order=["alertname", "severity", "Episodes", "Firing time", "Avg duration"], sort=("Firing time", True),
    overrides=[col("Firing time", unit="s"), col("Avg duration", unit="s"),
               col("severity", cell=TXT, mappings=vmap({"critical": ("critical", "red"), "warning": ("warning", "yellow")}))]), 12, 10)
tl = state_timeline("Alert timeline", [tgt('max by (alertname) (ALERTS{alertstate="firing", alertname!="Watchdog"})', "{{alertname}}")],
                    desc="When each alert was firing.", mappings=vmap({"1": ("firing", "red")}))
d.add(tl, 12, 10)

d.row("Changes — deploys and restarts in the selected range")
seen = 'count_over_time(container_last_seen{name!="", image!=""}[$__range])'
d.add(stat("Deploys", f'(count(count by (name, image) ({seen})) - count(count by (name) ({seen}))) or vector(0)', graph=False,
           desc="Image changes: a container that ran more than one image in the range (deploy or rollback)."), 6, 4)
d.add(stat("Restarts", 'sum(changes(container_start_time_seconds{name!=""}[$__range])) or vector(0)',
           th=steps((5, "yellow"), (20, "red")), graph=False), 6, 4)
d.add(stat("OOM kills", 'sum(increase(container_oom_events_total{name!=""}[$__range])) or vector(0)',
           th=steps((1, "red")), graph=False), 6, 4)
d.add(stat("Critical alerts after a deploy", f'count(count by (alertname) (ALERTS{{alertstate="firing", severity="critical"}}'
           f' and on () (count(count by (name, image) (count_over_time(container_last_seen{{name!="", image!=""}}[1h])))'
           f' > count(count by (name) (count_over_time(container_last_seen{{name!="", image!=""}}[1h])))))) or vector(0)',
           th=steps((1, "red")), graph=False,
           desc="Critical alerts firing now while some container changed image in the last hour: a likely bad deploy."), 6, 4)
d.add(table("Deploys and restarts by container", [
    tgt(f'count by (name) (count by (name, image) ({seen})) - 1', instant=True, fmt="table"),
    tgt('sum by (name) (changes(container_start_time_seconds{name!=""}[$__range]))', instant=True, fmt="table"),
    tgt('sum by (name) (increase(container_oom_events_total{name!=""}[$__range]))', instant=True, fmt="table"),
], desc="Only containers with at least one deploy or restart matter; sort by a column to find them.",
    rename={"Value #A": "Deploys", "Value #B": "Restarts", "Value #C": "OOM kills", "name": "Container"},
    order=["Container", "Deploys", "Restarts", "OOM kills"], sort=("Restarts", True),
    overrides=[col("Restarts", cell=TXT, th=steps((3, "yellow"), (10, "red"))), col("OOM kills", cell=TXT, th=steps((1, "red")))]), 24, 9)

d.write("SRE/sre.json")

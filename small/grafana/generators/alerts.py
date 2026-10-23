"""Alerts: what is firing now, alert history and statistics, and the health of the whole alerting pipeline
(Prometheus rules → vmalert (log rules) → Alertmanager → Telegram)."""
from lib import *

UID, SLUG = "alerts", "alerts"
F = 'alertname=~"$alertname", severity=~"$severity", alertname!="Watchdog"'
FIRING = f'ALERTS{{alertstate="firing", {F}}}'
P_NOW, P_STATS, P_AM, P_PROM, P_VMA, P_TG = 901, 902, 903, 904, 905, 906
SEV_MAP = vmap({"critical": ("critical", "red"), "warning": ("warning", "orange"), "info": ("info", "blue"), "none": ("none", "transparent")})

d = Dash(UID, "Alerts",
         "Everything about alerting: alerts firing now and for how long, history and statistics (noisiest, flapping, longest), "
         "and the health of each pipeline stage: Prometheus rules, vmalert (log rules), Alertmanager and Telegram delivery.",
         ["alerts", "alertmanager", "vmalert", "overview"],
         variables=[
             query_var("severity", "Severity", "label_values(ALERTS, severity)"),
             query_var("alertname", "Alert", 'label_values(ALERTS{severity=~"$severity"}, alertname)'),
         ])

d.row("Health — is anything firing, and does alerting itself work")
d.add(text("**Pipeline:** Prometheus rules (metrics) and vmalert (log rules) → **Alertmanager** (grouping, silences, inhibition) → **Telegram**. "
           "Grafana runs its own dead man's switch rules directly to Telegram, so they still fire when this pipeline is down. "
           "`Watchdog` must always be firing: if it is 0, alerts cannot reach you. Silence or inspect alerts in "
           "[Alertmanager](http://localhost:39093) · [vmalert](http://localhost:38880) · [Grafana alerting](/alerting/list)."), 24, 2)
d.add(stat("Critical firing", f'count(ALERTS{{alertstate="firing", severity="critical", alertname!="Watchdog"}}) or vector(0)', th=steps((1, "red")),
           link=view(UID, SLUG, P_NOW, "Firing now"), desc="Critical alerts firing now: loud Telegram message, repeated every hour."), 3, 4)
d.add(stat("Warning firing", f'count(ALERTS{{alertstate="firing", severity="warning"}}) or vector(0)', th=steps((1, "orange")),
           link=view(UID, SLUG, P_NOW, "Firing now"), desc="Warnings firing now: silent Telegram message, repeated every 4 hours."), 3, 4)
d.add(stat("Pending", 'count(ALERTS{alertstate="pending"}) or vector(0)', th=steps((1, "yellow")), color_mode="value",
           link=view(UID, SLUG, P_NOW, "Firing now"), desc="Condition is true but the rule's 'for' time has not passed yet: about to fire."), 3, 4)
d.add(stat("Watchdog", 'count(ALERTS{alertname="Watchdog", alertstate="firing"}) or vector(0)', th=steps((1, "green"), base="red"),
           mappings=vmap({"0": ("BROKEN", "red"), "1": ("OK", "green")}), graph=False,
           desc="Always-firing alert proving the rule → Alertmanager path works. BROKEN = alerts are not being evaluated."), 3, 4)
d.add(stat("Telegram failures (1h)", 'sum(increase(alertmanager_notifications_failed_total{integration="telegram"}[1h])) or vector(0)', th=steps((1, "red")),
           decimals=0, link=view(UID, SLUG, P_TG, "Delivery"), desc="Messages Alertmanager failed to deliver. Check the bot token, chat id and network."), 3, 4)
d.add(stat("Active silences", 'max(alertmanager_silences{state="active"}) or vector(0)', th=steps((1, "blue")), color_mode="value",
           link=view(UID, SLUG, P_AM, "Alertmanager"), desc="Silences hiding alerts right now. Forgotten silences hide real problems."), 3, 4)
d.add(stat("Rule failures (15m)", 'sum(increase(vmalert_execution_errors_total[15m])) or vector(0)',
           th=steps((1, "red")), decimals=0, link=view(UID, SLUG, P_PROM, "Rule evaluation"),
           desc="Rule group evaluations that errored (bad query, datasource down) in both vmalerts. A failing rule never fires."), 3, 4)
d.add(stat("Notifications dropped (1h)", 'sum(increase(vmalert_alerts_send_errors_total[1h])) or vector(0)',
           th=steps((1, "red")), decimals=0, link=view(UID, SLUG, P_PROM, "vmalert → Alertmanager"),
           desc="Alerts vmalert could not hand to Alertmanager."), 3, 4)

d.row("Firing now")
now = table("Firing now", [
    tgt(f'(time() - ALERTS_FOR_STATE{{{F}}}) and ignoring (alertstate) {FIRING}', instant=True, fmt="table"),
], desc="Every firing alert with its labels and how long it has been firing. Sorted by duration. Use the column filters to narrow down.",
    sort=("Firing for", True), merge=False, hide=("alertstate",), rename={"Value": "Firing for"},
    order=["severity", "alertname", "Firing for"],
    overrides=[col("severity", cell=BG, mappings=SEV_MAP, width=100), col("alertname", width=220),
               col("Firing for", unit="s", cell=TXT, th=steps((3600, "orange"), (86400, "red")), decimals=0)])
now["id"] = P_NOW
now["fieldConfig"]["defaults"]["noValue"] = "Nothing firing"
d.add(now, 24, 9)
d.add(state_timeline("Alert timeline", [tgt(f'max by (alertname, severity) ({FIRING})', "{{alertname}} ({{severity}})")],
                     desc="When each alert was firing over the selected range. Many short blocks = flapping.", mappings=vmap({"1": ("firing", "red")})), 24, 9)

d.row("Statistics — noisiest, flapping, longest")
st = table("Alert statistics (selected range)", [
    tgt(f'sum by (alertname, severity) (count_over_time({FIRING}[$__range:1m]))', instant=True, fmt="table"),
    tgt(f'sum by (alertname, severity) (changes(ALERTS_FOR_STATE{{{F}}}[$__range]) + 1)', instant=True, fmt="table"),
    tgt(f'count by (alertname, severity) (max by (alertname, severity, instance, name, job, datname, service) (max_over_time({FIRING}[$__range:1m])))', instant=True, fmt="table"),
], desc="Per alert over the selected range: total firing minutes (all series), times it started firing, and how many different targets it hit. "
        "Many starts with few minutes = flapping: raise 'for' or the threshold.",
    sort=("Firing minutes", True),
    rename={"Value #A": "Firing minutes", "Value #B": "Times fired", "Value #C": "Targets hit"},
    order=["alertname", "severity", "Firing minutes", "Times fired", "Targets hit"],
    overrides=[col("severity", cell=BG, mappings=SEV_MAP, width=100), col("Firing minutes", unit="m", cell=BAR, th=steps((60, "orange"), (600, "red"))),
               col("Times fired", cell=BG, th=steps((5, "yellow"), (20, "red")), decimals=0), col("Targets hit", decimals=0)])
st["id"] = P_STATS
d.add(st, 12, 9)
d.add(piechart("Firing by severity", [tgt(f'count by (severity) ({FIRING})', "{{severity}}", instant=True)], desc="Share of firing alerts by severity."), 6, 9)
d.add(piechart("Firing by job", [tgt(f'count by (job) ({FIRING})', "{{job}}", instant=True)], desc="Which part of the stack the firing alerts come from (empty job = log rules from vmalert)."), 6, 9)
d.add(ts("Firing alerts over time", [tgt(f'count by (severity) ({FIRING})', "{{severity}}"), tgt(f'count(ALERTS{{alertstate="pending", {F}}})', "pending")],
         stack=True, draw="bars", fill=70, desc="Number of firing alerts by severity.",
         overrides=[{"matcher": {"id": "byName", "options": "critical"}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}}]},
                    {"matcher": {"id": "byName", "options": "warning"}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "orange"}}]},
                    {"matcher": {"id": "byName", "options": "pending"}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "yellow"}}]}]), 16, 8)
d.add(bargauge("Top 10 by firing time", [tgt(f'topk(10, sum by (alertname) (count_over_time({FIRING}[$__range:1m])))', "{{alertname}}", instant=True)],
               unit="m", th=steps((60, "orange"), (600, "red")), desc="Alerts that were firing the longest in the selected range."), 8, 8)

d.row("Alertmanager — routing, silences, delivery")
d.add(stat("Alertmanager", 'max(up{job="alertmanager"})', th=steps((1, "green"), base="red"), mappings=vmap({"0": ("DOWN", "red"), "1": ("UP", "green")}), graph=False,
           desc="Scrape status of Alertmanager."), 4, 4)
d.add(stat("Config reload", 'min(alertmanager_config_last_reload_successful)', th=steps((1, "green"), base="red"), mappings=vmap({"0": ("FAILED", "red"), "1": ("OK", "green")}), graph=False,
           desc="Last config reload. FAILED = Alertmanager keeps the old config; check its logs."), 4, 4)
d.add(stat("Alerts in Alertmanager", 'sum(alertmanager_alerts{state="active"})', color_mode="value", th=steps(base="blue"), desc="Alerts Alertmanager currently holds as active."), 4, 4)
d.add(stat("Suppressed", 'sum(alertmanager_alerts{state="suppressed"}) or vector(0)', color_mode="value", th=steps((1, "blue")),
           desc="Alerts hidden by a silence or an inhibition rule (e.g. warnings hidden while the matching critical fires)."), 4, 4)
d.add(stat("Aggregation groups", 'sum(alertmanager_dispatcher_aggregation_groups)', color_mode="value", th=steps(base="blue"),
           desc="Distinct groups (by group_by labels). One group = one Telegram message thread."), 4, 4)
d.add(stat("Config last reloaded", 'time() - max(alertmanager_config_last_reload_success_timestamp_seconds)', unit="s", color_mode="value", th=steps(base="blue"), decimals=0), 4, 4)
am = ts("Notifications by integration", [tgt('sum by (integration) (rate(alertmanager_notifications_total[5m])) * 60', "{{integration}} sent"),
                                          tgt('sum by (integration) (rate(alertmanager_notifications_failed_total[5m])) * 60', "{{integration}} failed")],
        unit="short", draw="bars", fill=70, desc="Messages per minute sent and failed, per receiver integration.",
        overrides=[{"matcher": {"id": "byRegexp", "options": ".*failed"}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}}]}])
am["id"] = P_AM
d.add(am,12, 10)
tg = ts("Delivery latency (p50 / p95 / p99)", [tgt(f'histogram_quantile({q}, sum by (le) (rate(alertmanager_notification_latency_seconds_bucket[15m])))', f"p{int(q*100)}") for q in (0.5, 0.95, 0.99)],
        unit="s", fill=0, desc="Time Alertmanager needs to deliver a message to Telegram.")
tg["id"] = P_TG
d.add(tg,12, 10)
d.add(ts("Alerts received", [tgt('sum by (status) (rate(alertmanager_alerts_received_total[5m])) * 60', "{{status}}"),
                             tgt('sum(rate(alertmanager_alerts_invalid_total[5m])) * 60', "invalid")], draw="bars", fill=70,
         desc="Alert updates received per minute from Prometheus and vmalert. Senders resend firing alerts regularly, so this is never 0 while anything fires."),12, 10)
d.add(ts("Alerts by state", [tgt('sum by (state) (alertmanager_alerts)', "{{state}}")], stack=True, desc="active vs suppressed (silenced/inhibited) vs unprocessed."),12, 10)
d.add(ts("Silences", [tgt('max by (state) (alertmanager_silences)', "{{state}}")], desc="Silences by state. Expired ones are kept for a while, then garbage-collected."),12, 10)
d.add(ts("Suppressed notifications", [tgt('sum by (reason) (rate(alertmanager_notifications_suppressed_total[5m])) * 60', "{{reason}}")], draw="bars", fill=70,
         desc="Notifications not sent because of a silence, inhibition or the maintenance window (time_intervals)."),12, 10)

d.row("vmalert-metrics — metric rules (prometheus/rules, PromQL) evaluation and sending", collapsed=True)
pr = ts("Rule group evaluation time vs interval", [tgt('max by (group) (vmalert_iteration_duration_seconds{instance=~".*vmalert-metrics.*", quantile="0.99"}) / max by (group) (vmalert_iteration_interval_seconds{instance=~".*vmalert-metrics.*"})', "{{group}}")],
        unit="percentunit", th=steps((0.5, "yellow"), (0.9, "red")), fill=0,
        desc="How much of its interval each group needs (p99). Near 100% = the group cannot keep up and starts missing evaluations.")
pr["id"] = P_PROM
d.add(pr, 12, 8)
d.add(ts("Evaluation failures & missed iterations", [tgt('sum by (group) (increase(vmalert_execution_errors_total{instance=~".*vmalert-metrics.*"}[5m]))', "{{group}} failures"),
                                                    tgt('sum by (group) (increase(vmalert_iteration_missed_total{instance=~".*vmalert-metrics.*"}[5m]))', "{{group}} missed")],
         draw="bars", fill=70, desc="Should be 0. Failures = broken query; missed = group too slow."), 12, 8)
d.add(table("Rule groups", [
    tgt('count by (group) (vmalert_alerting_rules_last_evaluation_samples{instance=~".*vmalert-metrics.*"}) or count by (group) (vmalert_recording_rules_last_evaluation_samples{instance=~".*vmalert-metrics.*"})', instant=True, fmt="table"),
    tgt('max by (group) (vmalert_iteration_interval_seconds{instance=~".*vmalert-metrics.*"})', instant=True, fmt="table"),
    tgt('max by (group) (vmalert_iteration_duration_seconds{instance=~".*vmalert-metrics.*", quantile="0.99"})', instant=True, fmt="table"),
    tgt('sum by (group) (vmalert_alerting_rules_last_evaluation_samples{instance=~".*vmalert-metrics.*"}) or sum by (group) (vmalert_recording_rules_last_evaluation_samples{instance=~".*vmalert-metrics.*"})', instant=True, fmt="table"),
], desc="Every rule group loaded by vmalert-metrics (prometheus/rules/*.yml).", sort=("Duration p99", True),
    rename={"Value #A": "Rules", "Value #B": "Interval", "Value #C": "Duration p99", "Value #D": "Samples"},
    overrides=[col("group", width=380), col("Interval", unit="s"), col("Duration p99", unit="s", cell=TXT, th=steps((1, "yellow"), (10, "red")), decimals=3)]), 24, 8)
d.add(ts("vmalert-metrics → Alertmanager", [tgt('sum(rate(vmalert_alerts_sent_total{instance=~".*vmalert-metrics.*"}[5m])) * 60', "sent/min"),
                                           tgt('sum(rate(vmalert_alerts_send_errors_total{instance=~".*vmalert-metrics.*"}[5m])) * 60', "errors/min")], fill=0,
         desc="Alert notifications handed to Alertmanager. Errors > 0 = Alertmanager unreachable."), 12, 8)
d.add(ts("Remote write (recording rules + alert state → VictoriaMetrics)", [tgt('sum(rate(vmalert_remotewrite_sent_rows_total{instance=~".*vmalert-metrics.*"}[5m]))', "rows/s"),
      tgt('sum(rate(vmalert_remotewrite_errors_total{instance=~".*vmalert-metrics.*"}[5m])) + sum(rate(vmalert_remotewrite_dropped_rows_total{instance=~".*vmalert-metrics.*"}[5m]))', "errors+dropped/s")], fill=0), 12, 8)

d.row("vmalert — log rules (vmalert/rules, LogsQL)", collapsed=True)
vm = ts("Log alerts firing / pending", [tgt('sum(vmalert_alerts_firing)', "firing"), tgt('sum(vmalert_alerts_pending)', "pending")], fill=0,
        desc="Alerts from vmalert's LogsQL rules (vmalert/rules/*.yml).")
vm["id"] = P_VMA
d.add(vm, 8, 8)
d.add(ts("Rule executions & errors", [tgt('sum by (group) (rate(vmalert_execution_total[5m])) * 60', "{{group}} runs/min"),
                                      tgt('sum by (group) (rate(vmalert_execution_errors_total[5m])) * 60', "{{group}} errors/min")], fill=0,
         desc="Errors = the LogsQL query failed (syntax, VictoriaLogs down)."), 8, 8)
d.add(ts("Group iteration time vs interval", [tgt('max by (group) (vmalert_iteration_duration_seconds{quantile="0.99"}) / max by (group) (vmalert_iteration_interval_seconds)', "{{group}}")],
         unit="percentunit", th=steps((0.5, "yellow"), (0.9, "red")), fill=0, desc="p99 evaluation time as a share of the interval."), 8, 8)
d.add(ts("Sent to Alertmanager", [tgt('sum(rate(vmalert_alerts_sent_total[5m])) * 60', "sent/min"), tgt('sum(rate(vmalert_alerts_send_errors_total[5m])) * 60', "errors/min")], fill=0), 8, 8)
d.add(ts("Remote write (alert state → VictoriaMetrics)", [tgt('sum(rate(vmalert_remotewrite_sent_rows_total[5m]))', "rows/s"),
                                                           tgt('sum(rate(vmalert_remotewrite_errors_total[5m])) + sum(rate(vmalert_remotewrite_dropped_rows_total[5m]))', "errors+dropped/s")], fill=0,
         desc="vmalert stores ALERTS series in VictoriaMetrics; errors here mean log alerts vanish from this dashboard."), 8, 8)
d.add(stat("vmalert config", 'min(vmalert_config_last_reload_successful)', th=steps((1, "green"), base="red"), mappings=vmap({"0": ("FAILED", "red"), "1": ("OK", "green")}),
           graph=False, desc="Last rule file reload."), 8, 8)

d.row("Pipeline logs", collapsed=True)
d.add(vl_ts("Errors by component", 'service:~"alertmanager|vmalert|prometheus|grafana" level:(error OR fatal OR panic OR warn) | stats by (service, level) count()', "{{service}} {{level}}",
            desc="Warnings and errors logged by the alerting components."), 24, 7)
d.add(logs("Alerting component logs", 'service:~"alertmanager|vmalert|prometheus" level:(error OR fatal OR panic OR warn) | sort by (_time desc) | limit 300',
           desc="Recent warnings and errors: failed notifications, bad rules, config reload problems."), 24, 10)

d.write("SRE/alerts.json")

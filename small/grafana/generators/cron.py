"""Cron: scheduled / batch jobs (container.type=cron). Jobs push their result to the Pushgateway at the end of
every run — the standard Prometheus pattern for short-lived jobs:

    echo "cron_job_last_run_timestamp_seconds $(date +%s)
    cron_job_last_success_timestamp_seconds $(date +%s)   # only when the run succeeded
    cron_job_duration_seconds 42
    cron_job_exit_code 0" | curl --data-binary @- http://pushgateway:9091/metrics/job/<name>/instance/<host>
"""
from lib import *

UID, SLUG = "cron", "cron"
J = 'job=~"$job"'
NO = "No cron_job_* metrics in the Pushgateway yet — see the dashboard description"

d = Dash(UID, "Cron",
         "Scheduled and batch jobs: last run, last success, duration, exit code — pushed to the Pushgateway by the job itself. "
         "Push cron_job_last_run_timestamp_seconds, cron_job_last_success_timestamp_seconds (on success), cron_job_duration_seconds "
         "and cron_job_exit_code to http://pushgateway:9091/metrics/job/<name>/instance/<host>.",
         ["cron", "jobs", "services"], time_from="now-6h",
         variables=[project_var(), container_var(),
                    query_var("job", "Job", "label_values(cron_job_last_run_timestamp_seconds, job)")])


def empty(p, note=NO):
    p["fieldConfig"]["defaults"]["noValue"] = note
    return p


health_row(d, "cron")

d.row("Jobs")
d.add(empty(stat("Jobs", f"count(cron_job_last_run_timestamp_seconds{{{J}}})", color_mode="value", th=steps(base="blue"), graph=False)), 4, 4)
d.add(empty(stat("Failing now", f"count(cron_job_exit_code{{{J}}} != 0) or vector(0)", th=steps((1, "red")), graph=False,
                 desc="Jobs whose last run exited non-zero.")), 4, 4)
d.add(empty(stat("Oldest success", f"max(time() - cron_job_last_success_timestamp_seconds{{{J}}})", unit="s", decimals=0,
                 th=steps((3600, "orange"), (86400, "red")), graph=False, desc="The job that has gone longest without succeeding.")), 4, 4)
d.add(empty(stat("Longest run (last)", f"max(cron_job_duration_seconds{{{J}}})", unit="s", decimals=0, color_mode="value", th=steps(base="blue"))), 4, 4)
d.add(stat("Pushgateway", 'max(up{job="pushgateway"})', mappings=vmap({"0": ("DOWN", "red"), "1": ("UP", "green")}), graph=False,
           th=steps((1, "green"), base="red"), desc="If the Pushgateway is down, jobs can't report and look stale."), 4, 4)
d.add(empty(stat("Failed runs (range)", f"sum(changes(cron_job_last_run_timestamp_seconds{{{J}}}[$__range])) - sum(changes(cron_job_last_success_timestamp_seconds{{{J}}}[$__range]))",
                 decimals=0, th=steps((1, "orange"), (5, "red")), graph=False, desc="Runs in the range minus successful runs.")), 4, 4)

d.add(empty(table("Jobs (now)", [
    tgt(f"max by (job, instance) (time() - cron_job_last_run_timestamp_seconds{{{J}}})", instant=True, fmt="table"),
    tgt(f"max by (job, instance) (time() - cron_job_last_success_timestamp_seconds{{{J}}})", instant=True, fmt="table"),
    tgt(f"max by (job, instance) (cron_job_duration_seconds{{{J}}})", instant=True, fmt="table"),
    tgt(f"max by (job, instance) (cron_job_exit_code{{{J}}})", instant=True, fmt="table"),
    tgt(f"sum by (job, instance) (changes(cron_job_last_run_timestamp_seconds{{{J}}}[$__range]))", instant=True, fmt="table"),
], desc="One row per job: when it last ran, when it last succeeded, how long it took and how it ended.",
    rename={"job": "Job", "instance": "Host", "Value #A": "Last run (ago)", "Value #B": "Last success (ago)", "Value #C": "Duration",
            "Value #D": "Exit code", "Value #E": "Runs (range)"}, sort=("Last success (ago)", True),
    overrides=[col("Last run (ago)", unit="s", decimals=0), col("Last success (ago)", unit="s", decimals=0, th=steps((3600, "orange"), (86400, "red")),
                                                               cell={"type": "color-text"}),
               col("Duration", unit="s", decimals=0),
               col("Exit code", decimals=0, th=steps((1, "red")), cell={"type": "color-background", "mode": "basic"},
                   mappings=[{"type": "value", "options": {"0": {"text": "OK", "color": "green"}}}]),
               col("Runs (range)", decimals=0)])), 24, 8)

d.add(empty(ts("Duration by job", [tgt(f"max by (job) (cron_job_duration_seconds{{{J}}})", "{{job}}")], unit="s", fill=0, draw="points",
               desc="One point per run. A job that slowly takes longer = more data or a slow dependency.")), 12, 9)
d.add(empty(ts("Exit code by job", [tgt(f"max by (job) (cron_job_exit_code{{{J}}})", "{{job}}")], fill=0, draw="points",
               desc="0 = success. Anything else = the run failed.")), 12, 9)
d.add(empty(ts("Time since last success", [tgt(f"max by (job) (time() - cron_job_last_success_timestamp_seconds{{{J}}})", "{{job}}")], unit="s", fill=0,
               desc="Saw-tooth = healthy (drops to 0 at every success). A line that keeps climbing = the job stopped succeeding.")), 24, 9)

d.row("Logs")
d.add(logs("Job output (errors and warnings)", f'{type_logs("cron")} level:(error OR fatal OR panic OR warn) | sort by (_time desc) | limit 300'), 24, 10)

d.write("Apps/cron.json")

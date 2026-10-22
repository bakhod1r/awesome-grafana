"""Worker: background job processors (container.type=worker). Job metrics from the common libraries —
asynq (Go), Celery (celery-exporter), Sidekiq (yabeda), BullMQ — merged into one view, plus a log-based fallback
that works for any worker: log volume, errors and the most frequent error messages."""
from lib import *

UID, SLUG = "worker", "worker"
C = 'container=~"$container"'
NO_JOBS = "No job metrics (asynq / Celery / Sidekiq / BullMQ exporter) — see the log panels below"


def any_of(*exprs):
    return " or ".join(f"({e})" for e in exprs)


def empty(p, note=NO_JOBS):
    p["fieldConfig"]["defaults"]["noValue"] = "No job metrics" if p["type"] == "stat" else note
    return p


DONE = any_of(f'sum(rate(asynq_tasks_processed_total{{{C}}}[5m]))', f'sum(rate(celery_task_succeeded_total{{{C}}}[5m]))',
              f'sum(rate(sidekiq_jobs_executed_total{{{C}}}[5m]))', f'sum(rate(bullmq_job_count{{{C}, state="completed"}}[5m]))')
FAIL = any_of(f'sum(rate(asynq_tasks_failed_total{{{C}}}[5m]))', f'sum(rate(celery_task_failed_total{{{C}}}[5m]))',
              f'sum(rate(sidekiq_jobs_failed_total{{{C}}}[5m]))', f'sum(rate(bullmq_job_count{{{C}, state="failed"}}[5m]))')
WAIT = any_of(f'sum(asynq_queue_size{{{C}, state="pending"}})', f'sum(celery_queue_length{{{C}}})',
              f'sum(sidekiq_jobs_waiting_count{{{C}}})', f'sum(bullmq_job_count{{{C}, state="waiting"}})')
RETRY = any_of(f'sum(asynq_queue_size{{{C}, state="retry"}})', f'sum(sidekiq_jobs_retry_count{{{C}}})', f'sum(bullmq_job_count{{{C}, state="delayed"}})')
DEAD = any_of(f'sum(asynq_queue_size{{{C}, state="archived"}})', f'sum(sidekiq_jobs_dead_count{{{C}}})')
DUR = lambda q: any_of(f'histogram_quantile({q}, sum by (le) (rate(celery_task_runtime_bucket{{{C}}}[5m])))',
                       f'histogram_quantile({q}, sum by (le) (rate(sidekiq_job_runtime_seconds_bucket{{{C}}}[5m])))',
                       f'histogram_quantile({q}, sum by (le) (rate(job_duration_seconds_bucket{{{C}}}[5m])))')

d = Dash(UID, "Worker",
         "Background workers: jobs done and failed, backlog, retries, dead jobs, job duration — from asynq, Celery, Sidekiq or BullMQ "
         "metrics when present, and from the worker's logs always. Opened for containers labelled container.type=worker.",
         ["worker", "jobs", "services"], time_from="now-3h", variables=[project_var(), container_var()])

health_row(d, "worker")

d.row("Jobs")
d.add(empty(stat("Jobs done/s", DONE, unit="ops", color_mode="value", th=steps(base="blue"))), 4, 4)
d.add(empty(stat("Failed %", f"({FAIL}) / (({DONE}) + ({FAIL})) * 100", unit="percent", decimals=1, th=steps((1, "orange"), (5, "red")))), 4, 4)
d.add(empty(stat("Waiting", WAIT, color_mode="value", th=steps((100, "orange"), (1000, "red")), desc="Jobs queued, not started. Growing = add workers.")), 4, 4)
d.add(empty(stat("Retrying", RETRY, color_mode="value", th=steps((1, "orange")))), 4, 4)
d.add(empty(stat("Dead / archived", DEAD, color_mode="value", th=steps((1, "red")), desc="Gave up after all retries: needs a human.")), 4, 4)
d.add(empty(stat("p95 job time", DUR(0.95), unit="s", decimals=2, th=steps((10, "orange"), (60, "red")))), 4, 4)
d.add(empty(ts("Jobs/s: done vs failed", [tgt(DONE, "done"), tgt(FAIL, "failed")], unit="ops", fill=0,
               overrides=[{"matcher": {"id": "byName", "options": "failed"}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}}]}])), 12, 9)
d.add(empty(ts("Backlog", [tgt(WAIT, "waiting"), tgt(RETRY, "retrying"), tgt(DEAD, "dead")], fill=0,
               desc="Waiting climbing while done/s is flat = workers saturated.")), 12, 9)
d.add(empty(ts("Job duration p50 / p95 / p99", [tgt(DUR(q), f"p{int(q * 100)}") for q in (0.5, 0.95, 0.99)], unit="s", fill=0)), 12, 9)
d.add(empty(ts("Failed jobs/s by task", [tgt(any_of(f'sum by (name) (rate(celery_task_failed_total{{{C}}}[5m]))',
                                                    f'sum by (worker) (rate(sidekiq_jobs_failed_total{{{C}}}[5m]))',
                                                    f'sum by (task_type) (rate(asynq_tasks_failed_total{{{C}}}[5m]))'), "{{name}}{{worker}}{{task_type}}")],
               unit="ops", stack=True)), 12, 9)

d.row("From logs (works for any worker)")
LQ = type_logs("worker")
d.add(vl_ts("Log lines/min by level", f'{LQ} | stats by (level) count()', "{{level}}"), 12, 9)
d.add(vl_ts("Errors/min", f'{LQ} level:(error OR fatal OR panic) | stats count()', "errors"), 12, 9)
d.add(vl_table("Top error messages", f'{LQ} level:(error OR fatal OR panic) | unpack_logfmt fields (msg, err, error) keep_original_fields | format if (msg:"") "<_msg>" as msg | stats by (msg, err, error) count() hits | sort by (hits desc) | limit 15',
               desc="Same error many times = one broken job type.", sort=("hits", True)), 12, 9)
d.add(vl_table("Top log messages", f'{LQ} | stats by (msg) count() hits | sort by (hits desc) | limit 15',
               desc="What the worker spends its time logging (job started / done lines show the job mix).", sort=("hits", True)), 12, 9)
d.add(logs("Errors and warnings", f'{LQ} level:(error OR fatal OR panic OR warn) | sort by (_time desc) | limit 300'), 24, 10)

d.write("Apps/worker.json")

"""Storage: MinIO / S3-compatible object storage (MinIO's own /minio/v2/metrics/cluster endpoint)."""
from lib import *

UID, SLUG = "storage", "storage"
I = 'instance=~"$instance"'

d = Dash(UID, "Storage",
         "MinIO (S3-compatible object storage): health, capacity, objects, S3 requests, errors, latency and traffic. "
         "Scraped from /minio/v2/metrics/cluster; set MINIO_PROMETHEUS_AUTH_TYPE=public on the container and the labels "
         "prometheus.port=9000, prometheus.path=/minio/v2/metrics/cluster so the discoverer picks it up.",
         ["storage", "minio", "s3", "services"], time_from="now-3h",
         variables=[project_var(), query_var("instance", "Server", 'label_values(minio_cluster_health_status{project=~"$project"}, instance)',
                                             desc="MinIO server (one deployment).", include_all=False, multi=False)])

d.row("Health")
d.add(stat("Status", f"min(minio_cluster_health_status{{{I}}})", mappings=vmap({"0": ("DOWN", "red"), "1": ("UP", "green")}),
           th=steps((1, "green"), base="red"), desc="1 = cluster healthy (read and write quorum)."), 3, 4)
d.add(stat("Uptime", f"max(minio_node_process_uptime_seconds{{{I}}})", unit="s", color_mode="value", th=steps(base="blue")), 3, 4)
d.add(stat("Used", f"(1 - max(minio_cluster_capacity_usable_free_bytes{{{I}}}) / max(minio_cluster_capacity_usable_total_bytes{{{I}}})) * 100",
           unit="percent", decimals=1, th=steps((80, "orange"), (90, "red")), desc="Usable capacity in use. Writes fail when the disk is full."), 3, 4)
d.add(stat("Data stored", f"max(minio_cluster_usage_total_bytes{{{I}}})", unit="bytes", color_mode="value", th=steps(base="blue"),
           desc="Bytes in all buckets (scanner result, refreshes every few minutes)."), 3, 4)
d.add(stat("Objects", f"max(minio_cluster_usage_object_total{{{I}}})", color_mode="value", th=steps(base="blue")), 3, 4)
d.add(stat("Buckets", f"max(minio_cluster_bucket_total{{{I}}})", color_mode="value", th=steps(base="blue")), 3, 4)
d.add(stat("Drives offline", f"sum(minio_cluster_drive_offline_total{{{I}}})", th=steps((1, "red")), desc="Drives MinIO cannot reach."), 3, 4)
d.add(stat("S3 requests/s", f"sum(rate(minio_s3_requests_total{{{I}}}[5m]))", unit="reqps", color_mode="value", th=steps(base="blue")), 3, 4)

d.row("S3 traffic")
d.add(ts("Requests/s by API (top 10)", [tgt(f"topk(10, sum by (api) (rate(minio_s3_requests_total{{{I}}}[5m])))", "{{api}}")],
         unit="reqps", stack=True, desc="S3 calls per second by operation (getobject, putobject, listobjectsv2, ...)."), 12, 8)
d.add(ts("Errors/s", [tgt(f"sum(rate(minio_s3_requests_4xx_errors_total{{{I}}}[5m])) or vector(0)", "4xx"),
                      tgt(f"sum(rate(minio_s3_requests_5xx_errors_total{{{I}}}[5m])) or vector(0)", "5xx"),
                      tgt(f"sum(rate(minio_s3_requests_rejected_auth_total{{{I}}}[5m]))", "rejected: auth")],
         unit="reqps", desc="4xx: client mistakes (missing key, bad signature). 5xx: MinIO failed. Rejected auth: wrong access key."), 12, 8)
d.add(ts("Time to first byte p50 / p95 / p99",
         [tgt(f"histogram_quantile({q}, sum by (le) (rate(minio_s3_requests_ttfb_seconds_distribution{{{I}}}[5m])))", f"p{int(q * 100)}")
          for q in (0.5, 0.95, 0.99)], unit="s", fill=0, desc="How long MinIO takes to start answering an S3 call."), 12, 8)
d.add(ts("Traffic", [tgt(f"sum(rate(minio_s3_traffic_received_bytes{{{I}}}[5m]))", "received (uploads)"),
                     tgt(f"sum(rate(minio_s3_traffic_sent_bytes{{{I}}}[5m]))", "sent (downloads)")], unit="Bps"), 12, 8)
d.add(ts("In flight / waiting", [tgt(f"sum(minio_s3_requests_inflight_total{{{I}}})", "in flight"),
                                 tgt(f"sum(minio_s3_requests_waiting_total{{{I}}})", "waiting")],
         desc="Waiting > 0 for long: MinIO is at its request limit."), 12, 8)

d.row("Capacity")
d.add(ts("Usable capacity", [tgt(f"max(minio_cluster_capacity_usable_total_bytes{{{I}}})", "total"),
                             tgt(f"max(minio_cluster_capacity_usable_total_bytes{{{I}}}) - max(minio_cluster_capacity_usable_free_bytes{{{I}}})", "used")],
         unit="bytes", fill=0), 12, 8)
d.add(ts("Objects and data stored", [tgt(f"max(minio_cluster_usage_object_total{{{I}}})", "objects"),
                                     tgt(f"max(minio_cluster_usage_total_bytes{{{I}}})", "bytes")], fill=0,
         overrides=[{"matcher": {"id": "byName", "options": "bytes"}, "properties": [{"id": "unit", "value": "bytes"}, {"id": "custom.axisPlacement", "value": "right"}]}]), 12, 8)

d.row("Process")
d.add(ts("CPU", [tgt(f"sum(rate(minio_node_process_cpu_total_seconds{{{I}}}[5m]))", "cores")], unit="short", fill=10), 12, 8)
d.add(ts("Memory", [tgt(f"sum(minio_node_process_resident_memory_bytes{{{I}}})", "resident")], unit="bytes"), 12, 8)

d.row("Forecast")
d.add(stat("Disk full in", f"max(minio_cluster_capacity_usable_free_bytes{{{I}}}) / (-deriv(max(minio_cluster_capacity_usable_free_bytes{{{I}}})[6h:5m]) > 0)",
           unit="s", decimals=0, th=steps((86400, "red"), (7 * 86400, "orange"), (30 * 86400, "green"), base="red"),
           desc="At the 6h fill rate, time until no usable space is left. Empty = not filling up."), 6, 8)
d.add(ts("Capacity forecast (30 days)", [tgt(f"max(minio_cluster_capacity_usable_total_bytes{{{I}}}) - max(minio_cluster_capacity_usable_free_bytes{{{I}}})", "used"),
                                         tgt(f"max(minio_cluster_capacity_usable_total_bytes{{{I}}}) - predict_linear(max(minio_cluster_capacity_usable_free_bytes{{{I}}})[24h:5m], 30 * 86400)", "in 30 days (trend)"),
                                         tgt(f"max(minio_cluster_capacity_usable_total_bytes{{{I}}})", "total")], unit="bytes", fill=0), 18, 8)

d.write("Apps/storage.json")

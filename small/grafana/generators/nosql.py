"""NoSQL: MongoDB (percona mongodb_exporter, job mongodb) and Memcached (memcached-exporter, job memcached),
for containers labelled container.type=nosql."""
from lib import *

UID, SLUG = "nosql", "nosql"
P = 'project=~"$project"'

d = Dash(UID, "NoSQL",
         "MongoDB and Memcached: operations, latency, connections, cache memory and evictions. "
         "Opened for containers labelled container.type=nosql.",
         ["nosql", "mongodb", "memcached", "services"], time_from="now-3h", variables=[project_var(), container_var()])


def empty(p, note):
    p["fieldConfig"]["defaults"]["noValue"] = note
    return p


health_row(d, "nosql")

NO_M = "No MongoDB exporter scraped (prometheus/exporters/mongodb.yml)"
d.row("MongoDB")
d.add(stat("Status", f"max(mongodb_up{{{P}}})", mappings=vmap({"0": ("DOWN", "red"), "1": ("UP", "green")}), graph=False, th=steps((1, "green"), base="red")), 4, 4)
d.add(stat("Operations/s", f"sum(rate(mongodb_op_counters_total{{{P}, type!=\"command\"}}[5m]))", unit="ops", color_mode="value", th=steps(base="blue")), 4, 4)
d.add(stat("Connections", f"sum(mongodb_connections{{{P}, state=\"current\"}})", color_mode="value", th=steps(base="blue")), 4, 4)
d.add(stat("Connections free", f"sum(mongodb_connections{{{P}, state=\"available\"}})", color_mode="value", th=steps((100, "orange"), (1000, "green"), base="red")), 4, 4)
d.add(stat("Cache used", f"max(mongodb_mongod_wiredtiger_cache_bytes{{{P}, type=\"total\"}}) / max(mongodb_mongod_wiredtiger_cache_max_bytes{{{P}}}) * 100",
           unit="percent", decimals=0, th=steps((80, "orange"), (95, "red")), desc="WiredTiger cache. Near 100% = reads hit the disk."), 4, 4)
d.add(stat("Queued ops", f"sum(mongodb_mongod_global_lock_current_queue{{{P}}})", th=steps((1, "orange"), (10, "red")),
           desc="Operations waiting for a lock."), 4, 4)
d.add(empty(ts("Operations/s by type", [tgt(f"sum by (type) (rate(mongodb_op_counters_total{{{P}}}[5m]))", "{{type}}")], unit="ops", stack=True), NO_M), 12, 9)
d.add(empty(ts("Latency by operation (avg)", [tgt(f"sum by (type) (rate(mongodb_mongod_op_latencies_latency_total{{{P}}}[5m])) / "
                                                 f"sum by (type) (rate(mongodb_mongod_op_latencies_ops_total{{{P}}}[5m])) / 1e6", "{{type}}")],
               unit="s", fill=0, desc="reads, writes, commands: average time per operation."), NO_M), 12, 9)
d.add(empty(ts("Documents/s", [tgt(f"sum by (state) (rate(mongodb_mongod_metrics_document_total{{{P}}}[5m]))", "{{state}}")], unit="ops", stack=True,
               desc="returned / inserted / updated / deleted."), NO_M), 12, 9)
d.add(empty(ts("Query efficiency: scanned vs returned", [tgt(f"sum(rate(mongodb_mongod_metrics_query_executor_total{{{P}, state=\"scanned_objects\"}}[5m]))", "docs scanned/s"),
                                                         tgt(f"sum(rate(mongodb_mongod_metrics_query_executor_total{{{P}, state=\"scanned\"}}[5m]))", "index keys scanned/s"),
                                                         tgt(f"sum(rate(mongodb_mongod_metrics_document_total{{{P}, state=\"returned\"}}[5m]))", "docs returned/s")],
               unit="ops", fill=0, desc="Many docs scanned for few returned = queries without a fitting index (collection scans)."), NO_M), 12, 9)
d.add(empty(ts("Connections", [tgt(f"sum by (state) (mongodb_connections{{{P}, state=~\"current|active\"}})", "{{state}}")], fill=0), NO_M), 12, 9)
d.add(empty(ts("WiredTiger cache", [tgt(f"max(mongodb_mongod_wiredtiger_cache_bytes{{{P}, type=\"total\"}})", "used"),
                                    tgt(f"max(mongodb_mongod_wiredtiger_cache_bytes{{{P}, type=\"dirty\"}})", "dirty"),
                                    tgt(f"max(mongodb_mongod_wiredtiger_cache_max_bytes{{{P}}})", "max")], unit="bytes", fill=0), NO_M), 12, 9)

NO_MC = "No Memcached exporter scraped (prometheus/exporters/memcached.yml)"
d.row("Memcached")
d.add(stat("Status", f"max(memcached_up{{{P}}})", mappings=vmap({"0": ("DOWN", "red"), "1": ("UP", "green")}), graph=False, th=steps((1, "green"), base="red")), 4, 4)
d.add(stat("Hit ratio", f"sum(rate(memcached_commands_total{{{P}, command=\"get\", status=\"hit\"}}[5m])) / sum(rate(memcached_commands_total{{{P}, command=\"get\"}}[5m])) * 100",
           unit="percent", decimals=1, th=steps((50, "orange"), (80, "green"), base="red")), 4, 4)
d.add(stat("Memory used", f"max(memcached_current_bytes{{{P}}}) / max(memcached_limit_bytes{{{P}}}) * 100", unit="percent", decimals=0,
           th=steps((90, "orange"))), 4, 4)
d.add(stat("Evictions/s", f"sum(rate(memcached_items_evicted_total{{{P}}}[5m]))", decimals=2, th=steps((0.1, "orange")),
           desc="Items dropped to make room: the cache is too small."), 4, 4)
d.add(stat("Items", f"sum(memcached_current_items{{{P}}})", color_mode="value", th=steps(base="blue")), 4, 4)
d.add(stat("Connections", f"sum(memcached_current_connections{{{P}}}) / max(memcached_max_connections{{{P}}}) * 100", unit="percent", decimals=0,
           th=steps((80, "orange"), (95, "red")), desc="Against -c (max connections)."), 4, 4)
d.add(empty(ts("Commands/s by command and result", [tgt(f"sum by (command, status) (rate(memcached_commands_total{{{P}}}[5m]))", "{{command}} {{status}}")],
               unit="ops", stack=True), NO_MC), 12, 9)
d.add(empty(ts("Memory and evictions", [tgt(f"max(memcached_current_bytes{{{P}}})", "used"), tgt(f"max(memcached_limit_bytes{{{P}}})", "limit"),
                                        tgt(f"sum(rate(memcached_items_evicted_total{{{P}}}[5m]))", "evictions/s")], unit="bytes", fill=0,
               overrides=[{"matcher": {"id": "byName", "options": "evictions/s"}, "properties": [{"id": "unit", "value": "short"}, {"id": "custom.axisPlacement", "value": "right"}]}]), NO_MC), 12, 9)

d.write("Apps/nosql.json")

"""Redis: health, memory vs maxmemory, hit ratio, commands, latency, clients, evictions, keys (redis_exporter)."""
from lib import *

UID, SLUG = "redis", "redis"
I = 'instance=~"$instance"'

d = Dash(UID, "Redis",
         "Redis from redis_exporter (compose profile redis): memory against maxmemory, cache hit ratio, commands/s and latency, "
         "clients, evictions and expirations, keys per database. Demo cache + traffic come with the profile.",
         ["redis", "cache", "services"], time_from="now-3h",
         variables=[project_var(), query_var("instance", "Server", 'label_values(redis_up{project=~"$project"}, instance)', desc="redis_exporter target (one Redis server).")],
         annotations=[{"name": "Redis restart", "datasource": VM, "enable": True, "iconColor": "orange",
                       "expr": f"changes(redis_uptime_in_seconds{{{I}}}[2m]) > 0 and redis_uptime_in_seconds{{{I}}} < 120", "step": "60s",
                       "titleFormat": "Redis restarted"}])

d.row("Health")
d.add(stat("Status", f"redis_up{{{I}}}", graph=False, mappings=vmap({"0": ("DOWN", "red"), "1": ("UP", "green")}), th=steps((1, "green"), base="red"),
           desc="1 = exporter reaches Redis."), 3, 4)
d.add(stat("Uptime", f"redis_uptime_in_seconds{{{I}}}", unit="s", graph=False, color_mode="value", th=steps(base="blue")), 3, 4)
d.add(stat("Memory used / max", f"redis_memory_used_bytes{{{I}}} / (redis_memory_max_bytes{{{I}}} > 0) * 100", unit="percent", decimals=0,
           th=steps((80, "orange"), (95, "red")), desc="Share of maxmemory. Empty when maxmemory is 0 (no limit): then the host RAM is the limit."), 3, 4)
d.add(stat("Hit ratio (5m)", f"sum(rate(redis_keyspace_hits_total{{{I}}}[5m])) / (sum(rate(redis_keyspace_hits_total{{{I}}}[5m])) + sum(rate(redis_keyspace_misses_total{{{I}}}[5m]))) * 100",
           unit="percent", decimals=1, th=steps((50, "orange"), (80, "green"), base="red"), desc="Reads that found the key. Low = cache too small or wrong keys."), 3, 4)
d.add(stat("Commands/s", f"sum(rate(redis_commands_processed_total{{{I}}}[5m]))", unit="ops", color_mode="value", th=steps(base="blue")), 3, 4)
d.add(stat("Clients", f"sum(redis_connected_clients{{{I}}})", color_mode="value", th=steps(base="blue"), desc="Open client connections."), 3, 4)
d.add(stat("Evictions/s", f"sum(rate(redis_evicted_keys_total{{{I}}}[5m]))", unit="ops", decimals=1, th=steps((0.01, "orange")),
           desc="Keys dropped because memory hit maxmemory. Fine for a pure cache; data loss for anything else."), 3, 4)
d.add(stat("Keys", f"sum(redis_db_keys{{{I}}})", color_mode="value", th=steps(base="blue")), 3, 4)

d.row("Memory")
d.add(ts("Memory", [tgt(f"redis_memory_used_bytes{{{I}}}", "used"), tgt(f"redis_memory_used_rss_bytes{{{I}}}", "rss (from OS)"),
                    tgt(f"redis_memory_max_bytes{{{I}}} > 0", "maxmemory")], unit="bytes", fill=0,
         overrides=[{"matcher": {"id": "byName", "options": "maxmemory"}, "properties": [
             {"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [8, 6]}}, {"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}}]}],
         desc="used = data + overhead; rss = what the OS sees. When used reaches maxmemory the eviction policy kicks in."), 12, 8)
d.add(ts("Fragmentation ratio", [tgt(f"redis_mem_fragmentation_ratio{{{I}}}", "rss / used")], th=steps((1.5, "orange")), minv=0, fill=0,
         desc="Above ~1.5: memory is wasted in fragments (activedefrag or a restart helps). Below 1: Redis is swapping."), 12, 8)

d.row("Traffic")
d.add(ts("Commands/s by command (top 10)", [tgt(f"topk(10, sum by (cmd) (rate(redis_commands_total{{{I}}}[5m])))", "{{cmd}}")], unit="ops", stack=True), 12, 8)
d.add(ts("Average latency by command (top 10)",
         [tgt(f"topk(10, sum by (cmd) (rate(redis_commands_duration_seconds_total{{{I}}}[5m])) / sum by (cmd) (rate(redis_commands_total{{{I}}}[5m])))", "{{cmd}}")],
         unit="s", fill=0, desc="Time Redis spends executing each command (network not included). Slow ones block every other client."), 12, 8)
d.add(ts("Hits vs misses", [tgt(f"sum(rate(redis_keyspace_hits_total{{{I}}}[5m]))", "hits"), tgt(f"sum(rate(redis_keyspace_misses_total{{{I}}}[5m]))", "misses")],
         unit="ops", stack=True, overrides=[{"matcher": {"id": "byName", "options": "misses"}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "orange"}}]},
                                             {"matcher": {"id": "byName", "options": "hits"}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "green"}}]}]), 8, 8)
d.add(ts("Evicted and expired keys/s", [tgt(f"sum(rate(redis_evicted_keys_total{{{I}}}[5m]))", "evicted (memory full)"),
                                        tgt(f"sum(rate(redis_expired_keys_total{{{I}}}[5m]))", "expired (TTL)")], unit="ops", fill=0), 8, 8)
d.add(ts("Network", [tgt(f"sum(rate(redis_net_input_bytes_total{{{I}}}[5m]))", "in"), tgt(f"sum(rate(redis_net_output_bytes_total{{{I}}}[5m]))", "out")], unit="Bps", fill=0), 8, 8)

d.row("Clients and keys")
d.add(ts("Clients", [tgt(f"sum(redis_connected_clients{{{I}}})", "connected"), tgt(f"sum(redis_blocked_clients{{{I}}})", "blocked (BLPOP etc.)"),
                     tgt(f"redis_config_maxclients{{{I}}}", "maxclients")], fill=0), 8, 8)
d.add(ts("Rejected connections/s", [tgt(f"sum(rate(redis_rejected_connections_total{{{I}}}[5m]))", "rejected")], unit="ops", fill=0, th=steps((0.001, "red")),
         desc="Connections refused because maxclients was reached."), 8, 8)
d.add(ts("Keys per database", [tgt(f"sum by (db) (redis_db_keys{{{I}}})", "{{db}}"), tgt(f"sum by (db) (redis_db_keys_expiring{{{I}}})", "{{db}} with TTL")], fill=0), 8, 8)
d.add(ts("Slow log entries", [tgt(f"redis_slowlog_length{{{I}}}", "in slowlog")], fill=0,
         desc="Commands slower than slowlog-log-slower-than (default 10ms). See them with: redis-cli SLOWLOG GET 10"), 12, 7)
d.add(logs("Redis logs", 'service:~"redis.*" | sort by (_time desc) | limit 200', desc="Container logs of Redis and its exporter."), 12, 7)

d.row("Capacity and forecast")
d.add(stat("Clients vs maxclients", f"sum(redis_connected_clients{{{I}}}) / max(redis_config_maxclients{{{I}}}) * 100", unit="percent", decimals=1,
           th=steps((70, "orange"), (90, "red")), desc="At 100% new connections are refused."), 6, 4)
d.add(stat("Memory full in", f"(max(redis_memory_max_bytes{{{I}}} > 0) - max(redis_memory_used_bytes{{{I}}})) / (deriv(max(redis_memory_used_bytes{{{I}}})[6h:5m]) > 0)",
           unit="s", decimals=0, th=steps((86400, "red"), (7 * 86400, "orange"), (30 * 86400, "green"), base="red"),
           desc="At the 6h growth rate, time until used memory reaches maxmemory. Empty = not growing or no maxmemory."), 6, 4)
d.add(stat("Slowlog entries", f"max(redis_slowlog_length{{{I}}})", color_mode="value", th=steps((10, "orange"), (100, "red")),
           desc="Commands slower than slowlog-log-slower-than (default 10 ms) kept in the slowlog."), 6, 4)
d.add(stat("Hit ratio (24h)", f"sum(increase(redis_keyspace_hits_total{{{I}}}[24h])) / (sum(increase(redis_keyspace_hits_total{{{I}}}[24h])) + sum(increase(redis_keyspace_misses_total{{{I}}}[24h]))) * 100",
           unit="percent", decimals=1, th=steps((50, "orange"), (80, "green"), base="red")), 6, 4)
d.add(ts("Memory forecast (7 days)", [tgt(f"max(redis_memory_used_bytes{{{I}}})", "used"),
                                      tgt(f"predict_linear(max(redis_memory_used_bytes{{{I}}})[24h:5m], 7 * 86400)", "in 7 days (trend)"),
                                      tgt(f"max(redis_memory_max_bytes{{{I}}} > 0)", "maxmemory")], unit="bytes", fill=0,
         desc="Straight-line projection of the last 24h."), 12, 8)
d.add(ts("Hit ratio over time", [tgt(f"sum(rate(redis_keyspace_hits_total{{{I}}}[15m])) / (sum(rate(redis_keyspace_hits_total{{{I}}}[15m])) + sum(rate(redis_keyspace_misses_total{{{I}}}[15m]))) * 100", "hit %")],
         unit="percent", fill=0, minv=0, maxv=100, desc="A drop after a deploy = cache keys changed or TTLs too short."), 12, 8)

d.write("Apps/redis.json")

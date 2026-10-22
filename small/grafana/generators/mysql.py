"""MySQL / MariaDB: health, connections, queries, slow queries, InnoDB buffer pool, row locks, temp tables (mysqld-exporter)."""
from lib import *

UID, SLUG = "mysql", "mysql"
I = 'instance=~"$instance"'
G = "mysql_global_status_"

d = Dash(UID, "MySQL",
         "MySQL / MariaDB from mysqld-exporter (compose profile mysql): connections against max_connections, queries/s by type, "
         "slow queries, InnoDB buffer pool hit ratio, row lock waits, temp tables on disk, replication lag. Demo database + traffic come with the profile.",
         ["mysql", "database", "services"], time_from="now-3h",
         variables=[project_var(), query_var("instance", "Server", 'label_values(mysql_up{project=~"$project"}, instance)', desc="mysqld-exporter target (one MySQL server).")],
         annotations=[{"name": "MySQL restart", "datasource": VM, "enable": True, "iconColor": "orange",
                       "expr": f"{G}uptime{{{I}}} < 120", "step": "60s", "titleFormat": "MySQL restarted"}])

d.row("Health")
d.add(stat("Status", f"mysql_up{{{I}}}", graph=False, mappings=vmap({"0": ("DOWN", "red"), "1": ("UP", "green")}), th=steps((1, "green"), base="red"),
           desc="1 = exporter reaches MySQL."), 3, 4)
d.add(stat("Uptime", f"{G}uptime{{{I}}}", unit="s", graph=False, color_mode="value", th=steps(base="blue")), 3, 4)
d.add(stat("Connections used", f"{G}threads_connected{{{I}}} / mysql_global_variables_max_connections{{{I}}} * 100", unit="percent", decimals=0,
           th=steps((80, "orange"), (95, "red")), desc="threads_connected / max_connections. At 100% new clients get 'Too many connections'."), 3, 4)
d.add(stat("Queries/s", f"sum(rate({G}queries{{{I}}}[5m]))", unit="ops", color_mode="value", th=steps(base="blue")), 3, 4)
d.add(stat("Running threads", f"{G}threads_running{{{I}}}", color_mode="value", th=steps((10, "orange"), (30, "red")),
           desc="Queries executing right now. Steady growth = queries pile up (locks, slow disk)."), 3, 4)
d.add(stat("Slow queries (1h)", f"increase({G}slow_queries{{{I}}}[1h])", decimals=0, th=steps((1, "orange"), (50, "red")),
           desc="Queries slower than long_query_time."), 3, 4)
d.add(stat("Buffer pool hit", f"(1 - rate({G}innodb_buffer_pool_reads{{{I}}}[5m]) / rate({G}innodb_buffer_pool_read_requests{{{I}}}[5m])) * 100",
           unit="percent", decimals=2, th=steps((95, "orange"), (99, "green"), base="red"),
           desc="Page reads served from memory. Below ~99% the working set does not fit innodb_buffer_pool_size."), 3, 4)
d.add(stat("Row lock waits/s", f"rate({G}innodb_row_lock_waits{{{I}}}[5m])", unit="ops", decimals=2, th=steps((1, "orange"), (10, "red")),
           desc="Statements that had to wait for a row lock held by another transaction."), 3, 4)

d.row("Connections and queries")
d.add(ts("Connections", [tgt(f"{G}threads_connected{{{I}}}", "connected"), tgt(f"{G}threads_running{{{I}}}", "running"),
                         tgt(f"mysql_global_variables_max_connections{{{I}}}", "max_connections")], fill=0,
         overrides=[{"matcher": {"id": "byName", "options": "max_connections"}, "properties": [
             {"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [8, 6]}}, {"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}}]}]), 8, 8)
d.add(ts("Queries/s by command (top 10)", [tgt(f"topk(10, rate({G}commands_total{{{I}}}[5m]) > 0)", "{{command}}")], unit="ops", stack=True), 8, 8)
d.add(ts("Rows/s by operation", [tgt(f"sum by (operation) (rate({G}innodb_row_ops_total{{{I}}}[5m]))", "{{operation}}")], unit="ops", fill=0,
         desc="InnoDB rows read / inserted / updated / deleted. Many reads per query = missing index."), 8, 8)
d.add(ts("Slow queries", [tgt(f"rate({G}slow_queries{{{I}}}[5m]) * 60", "slow / min")], fill=0, draw="bars",
         desc="Turn on slow_query_log to see which ones (mysql/ has the demo settings)."), 8, 7)
d.add(ts("Aborted connections", [tgt(f"rate({G}aborted_connects{{{I}}}[5m]) * 60", "failed logins / min"),
                                 tgt(f"rate({G}aborted_clients{{{I}}}[5m]) * 60", "clients gone without closing / min")], fill=0,
         desc="Failed logins (wrong password, host not allowed) and clients that died mid-connection."), 8, 7)
d.add(ts("Bad query patterns", [tgt(f"rate({G}select_full_join{{{I}}}[5m]) * 60", "joins without index / min"),
                                tgt(f"rate({G}created_tmp_disk_tables{{{I}}}[5m]) * 60", "temp tables on disk / min"),
                                tgt(f"rate({G}sort_merge_passes{{{I}}}[5m]) * 60", "sort merge passes / min")], fill=0,
         desc="Signs of missing indexes or too small tmp_table_size / sort_buffer_size."), 8, 7)

d.row("InnoDB")
d.add(ts("Buffer pool pages", [tgt(f"sum by (state) ({G}buffer_pool_pages{{{I}}})", "{{state}}")],
         stack=True, desc="data = cached table/index pages, free = unused. Free near 0 and hit ratio dropping = pool too small."), 8, 8)
d.add(ts("Buffer pool reads", [tgt(f"rate({G}innodb_buffer_pool_read_requests{{{I}}}[5m])", "from memory"),
                               tgt(f"rate({G}innodb_buffer_pool_reads{{{I}}}[5m])", "from disk")], unit="ops", fill=0), 8, 8)
d.add(ts("Row lock time", [tgt(f"rate({G}innodb_row_lock_time{{{I}}}[5m]) / 1000", "seconds waited per second"),
                           tgt(f"{G}innodb_row_lock_current_waits{{{I}}}", "waiting now")], fill=0,
         desc="Total time statements spent waiting for row locks. Long waits: look for long transactions."), 8, 8)
d.add(ts("Network", [tgt(f"rate({G}bytes_received{{{I}}}[5m])", "received"), tgt(f"rate({G}bytes_sent{{{I}}}[5m])", "sent")], unit="Bps", fill=0), 12, 7)
rl = d.add(ts("Replication lag", [tgt(f"mysql_slave_status_seconds_behind_master{{{I}}} or mysql_replica_status_seconds_behind_source{{{I}}}", "{{channel_name}}")],
         unit="s", fill=0, th=steps((30, "orange"), (300, "red")), desc="Only on replicas. Empty on a primary / standalone server."), 12, 7)
rl["fieldConfig"]["defaults"]["noValue"] = "Not a replica"
d.add(logs("MySQL logs", 'service:~"mysql.*" | sort by (_time desc) | limit 200', desc="Container logs of MySQL and its exporter."), 24, 8)

d.write("Apps/mysql.json")

"""Search: Elasticsearch / OpenSearch (container.type=search), from elasticsearch-exporter (job elasticsearch)."""
from lib import *

UID, SLUG = "search", "search"
P = 'project=~"$project"'
IX = f'{P}, index=~"$index"'

d = Dash(UID, "Search",
         "Elasticsearch / OpenSearch: cluster health, shards, search and indexing speed, JVM heap, disk watermarks, "
         "caches and rejected work. From elasticsearch-exporter. Opened for containers labelled container.type=search.",
         ["search", "elasticsearch", "services"], time_from="now-3h",
         variables=[project_var(), container_var(),
                    query_var("index", "Index", 'label_values(elasticsearch_indices_docs_primary{project=~"$project"}, index)')])

health_row(d, "search")

d.row("Cluster")
d.add(stat("Health", f"max(elasticsearch_cluster_health_status{{{P}, color=\"green\"}}) * 2 + max(elasticsearch_cluster_health_status{{{P}, color=\"yellow\"}})",
           mappings=vmap({"0": ("RED", "red"), "1": ("YELLOW", "orange"), "2": ("GREEN", "green")}), graph=False,
           th=steps((1, "orange"), (2, "green"), base="red"),
           desc="GREEN all shards placed. YELLOW replicas missing (normal on one node). RED a primary shard is missing: data unavailable."), 4, 4)
d.add(stat("Nodes", f"max(elasticsearch_cluster_health_number_of_nodes{{{P}}})", color_mode="value", th=steps(base="blue"), graph=False), 4, 4)
d.add(stat("Unassigned shards", f"max(elasticsearch_cluster_health_unassigned_shards{{{P}}})", th=steps((1, "orange")), graph=False), 4, 4)
d.add(stat("Documents", f"sum(elasticsearch_indices_docs_primary{{{IX}}})", color_mode="value", th=steps(base="blue")), 4, 4)
d.add(stat("JVM heap", f"max(elasticsearch_jvm_memory_used_bytes{{{P}, area=\"heap\"}} / elasticsearch_jvm_memory_max_bytes{{{P}, area=\"heap\"}}) * 100",
           unit="percent", decimals=0, th=steps((75, "orange"), (90, "red")), desc="Constantly over 75% = long GC pauses, then circuit breakers trip."), 4, 4)
d.add(stat("Disk used", f"max(1 - elasticsearch_filesystem_data_available_bytes{{{P}}} / elasticsearch_filesystem_data_size_bytes{{{P}}}) * 100",
           unit="percent", decimals=0, th=steps((85, "orange"), (90, "red")),
           desc="85% = no new shards on this node, 90% = shards move away, 95% = indices become read-only."), 4, 4)

d.row("Search and indexing")
d.add(ts("Searches/s by index", [tgt(f"sum by (index) (rate(elasticsearch_index_stats_search_query_total{{{IX}}}[5m]))", "{{index}}")], unit="ops", stack=True), 12, 9)
d.add(ts("Search latency (avg per query)", [tgt(f"sum by (index) (rate(elasticsearch_index_stats_search_query_time_seconds_total{{{IX}}}[5m])) / "
                                                 f"sum by (index) (rate(elasticsearch_index_stats_search_query_total{{{IX}}}[5m]))", "{{index}}")],
         unit="s", fill=0, desc="Query phase time per search. Wildcards and big aggregations push it up."), 12, 9)
d.add(ts("Indexed docs/s by index", [tgt(f"sum by (index) (rate(elasticsearch_index_stats_indexing_index_total{{{IX}}}[5m]))", "{{index}}")], unit="ops", stack=True), 12, 9)
d.add(ts("Indexing latency (avg per doc)", [tgt(f"sum by (index) (rate(elasticsearch_index_stats_indexing_index_time_seconds_total{{{IX}}}[5m])) / "
                                                 f"sum by (index) (rate(elasticsearch_index_stats_indexing_index_total{{{IX}}}[5m]))", "{{index}}")], unit="s", fill=0), 12, 9)
d.add(ts("Rejected work (thread pools)", [tgt(f"sum by (type) (rate(elasticsearch_thread_pool_rejected_count{{{P}}}[5m]))", "{{type}}")], fill=0,
         desc="search / write rejections = the node is overloaded: clients get 429."), 12, 9)
d.add(ts("Caches: query cache hit %", [tgt(f"sum(rate(elasticsearch_index_stats_query_cache_hits_total{{{IX}}}[5m])) / (sum(rate(elasticsearch_index_stats_query_cache_hits_total{{{IX}}}[5m])) + sum(rate(elasticsearch_index_stats_query_cache_misses_total{{{IX}}}[5m]))) * 100", "query cache"),
                                       tgt(f"sum(rate(elasticsearch_index_stats_request_cache_hits_total{{{IX}}}[5m])) / (sum(rate(elasticsearch_index_stats_request_cache_hits_total{{{IX}}}[5m])) + sum(rate(elasticsearch_index_stats_request_cache_misses_total{{{IX}}}[5m]))) * 100", "request cache")],
         unit="percent", fill=0, minv=0, maxv=100), 12, 9)
d.panels[-1]["fieldConfig"]["defaults"]["noValue"] = "Caches not used yet (only filter and aggregation queries are cached)"

d.row("Indices and JVM")
d.add(table("Indices", [tgt(f"sum by (index) (elasticsearch_indices_docs_primary{{{IX}}})", instant=True, fmt="table"),
                        tgt(f"sum by (index) (elasticsearch_indices_store_size_bytes_primary{{{IX}}})", instant=True, fmt="table"),
                        tgt(f"sum by (index) (rate(elasticsearch_index_stats_search_query_total{{{IX}}}[5m]))", instant=True, fmt="table"),
                        tgt(f"sum by (index) (rate(elasticsearch_index_stats_indexing_index_total{{{IX}}}[5m]))", instant=True, fmt="table")],
            rename={"index": "Index", "Value #A": "Docs", "Value #B": "Size", "Value #C": "Searches/s", "Value #D": "Indexed/s"}, sort=("Size", True),
            overrides=[col("Size", unit="bytes"), col("Searches/s", decimals=2), col("Indexed/s", decimals=2)]), 12, 9)
d.add(ts("JVM heap and GC", [tgt(f"max(elasticsearch_jvm_memory_used_bytes{{{P}, area=\"heap\"}})", "heap used"),
                             tgt(f"max(elasticsearch_jvm_memory_max_bytes{{{P}, area=\"heap\"}})", "heap max"),
                             tgt(f"sum(rate(elasticsearch_jvm_gc_collection_seconds_sum{{{P}}}[5m]))", "gc time/s")], unit="bytes", fill=0,
         overrides=[{"matcher": {"id": "byName", "options": "gc time/s"}, "properties": [{"id": "unit", "value": "percentunit"}, {"id": "custom.axisPlacement", "value": "right"}]}]), 12, 9)

d.write("Apps/search.json")

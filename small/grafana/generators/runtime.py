"""Runtime dashboards, one per language (container.lang label): Go, Java, Node.js, Python, PHP, .NET, Rust, Ruby.

Each reads the default metrics the language's standard Prometheus client exposes on /metrics (found by the
discoverer, job "apps"), plus process_* and the container's cAdvisor numbers. Opened from the "Lang" column of
"Containers by type" on the Docker projects dashboard: /d/runtime-<lang>?var-container=<name>.
"""
from lib import *

C = 'container=~"$container", container!=""'  # apps job: container label set by the discoverer
N = 'name=~"$container"'               # cAdvisor: container name

VARS = [project_var(),
        query_var("container", "Container", 'label_values(up{job="apps", project=~"$project"}, container)',
                  desc="Container scraped by the discoverer (job apps).")]


def common(d):
    d.row("Process")
    d.add(stat("Uptime", f"max(time() - process_start_time_seconds{{{C}}})", unit="s", graph=False, color_mode="value", th=steps(base="blue")), 4, 4)
    d.add(stat("CPU", f"sum(rate(process_cpu_seconds_total{{{C}}}[5m]))", unit="short", decimals=2, color_mode="value", th=steps(base="blue"),
               desc="CPU cores used by the process."), 4, 4)
    d.add(stat("Resident memory", f"sum(process_resident_memory_bytes{{{C}}})", unit="bytes", color_mode="value", th=steps(base="blue")), 4, 4)
    d.add(stat("Open files", f"sum(process_open_fds{{{C}}}) / sum(process_max_fds{{{C}}}) * 100", unit="percent", decimals=1,
               th=steps((70, "orange"), (90, "red")), desc="Open file descriptors against the limit. 100% = can't accept connections."), 4, 4)
    d.add(stat("Container CPU", f"sum(rate(container_cpu_usage_seconds_total{{{N}}}[5m]))", decimals=2, color_mode="value", th=steps(base="blue"),
               desc="Whole container (cAdvisor), cores."), 4, 4)
    d.add(stat("Container memory", f"sum(container_memory_working_set_bytes{{{N}}})", unit="bytes", color_mode="value", th=steps(base="blue")), 4, 4)
    d.add(ts("CPU and memory", [tgt(f"sum by (container) (rate(process_cpu_seconds_total{{{C}}}[5m]))", "{{container}} cpu cores"),
                                tgt(f"sum by (container) (process_resident_memory_bytes{{{C}}})", "{{container}} resident")], fill=0,
             overrides=[{"matcher": {"id": "byRegexp", "options": ".*resident"}, "properties": [
                 {"id": "unit", "value": "bytes"}, {"id": "custom.axisPlacement", "value": "right"}]}]), 24, 8)


LANGS = {
    "go": ("Go", "Go client (prometheus/client_golang) default metrics.", [
        ("Goroutines", [(f"sum by (container) (go_goroutines{{{C}}})", "{{container}}")], "short",
         "Steady growth = goroutine leak (blocked channel, missing context cancel)."),
        ("Heap in use", [(f"sum by (container) (go_memstats_heap_inuse_bytes{{{C}}})", "{{container}} in use"),
                         (f"sum by (container) (go_memstats_heap_alloc_bytes{{{C}}})", "{{container}} allocated")], "bytes", ""),
        ("GC pause (avg)", [(f"sum by (container) (rate(go_gc_duration_seconds_sum{{{C}}}[5m])) / sum by (container) (rate(go_gc_duration_seconds_count{{{C}}}[5m]))", "{{container}}")],
         "s", "Average stop-the-world pause per GC cycle."),
        ("Allocation rate", [(f"sum by (container) (rate(go_memstats_alloc_bytes_total{{{C}}}[5m]))", "{{container}}")], "Bps",
         "Bytes allocated per second. High = more GC work."),
        ("OS threads", [(f"sum by (container) (go_threads{{{C}}})", "{{container}}")], "short", ""),
        ("GC cycles/s", [(f"sum by (container) (rate(go_gc_duration_seconds_count{{{C}}}[5m]))", "{{container}}")], "short", ""),
    ]),
    "java": ("Java", "JVM metrics from Micrometer (Spring Boot actuator/prometheus) or the JMX exporter.", [
        ("Heap used / max", [(f"sum by (container) (jvm_memory_used_bytes{{{C}, area=\"heap\"}}) or sum by (container) (jvm_memory_bytes_used{{{C}, area=\"heap\"}})", "{{container}} used"),
                             (f"sum by (container) (jvm_memory_max_bytes{{{C}, area=\"heap\"}}) or sum by (container) (jvm_memory_bytes_max{{{C}, area=\"heap\"}})", "{{container}} max")],
         "bytes", "Used near max for long = frequent full GCs, then OutOfMemoryError."),
        ("Non-heap (metaspace, code cache)", [(f"sum by (container) (jvm_memory_used_bytes{{{C}, area=\"nonheap\"}}) or sum by (container) (jvm_memory_bytes_used{{{C}, area=\"nonheap\"}})", "{{container}}")], "bytes", ""),
        ("GC pause time per second", [(f"sum by (container, action) (rate(jvm_gc_pause_seconds_sum{{{C}}}[5m]))", "{{container}} {{action}}"),
                                      (f"sum by (container, gc) (rate(jvm_gc_collection_seconds_sum{{{C}}}[5m]))", "{{container}} {{gc}}")],
         "percentunit", "Share of wall time spent in GC. Over 5% hurts latency."),
        ("Threads", [(f"sum by (container) (jvm_threads_live_threads{{{C}}}) or sum by (container) (jvm_threads_current{{{C}}})", "{{container}} live"),
                     (f"sum by (container) (jvm_threads_states_threads{{{C}, state=\"blocked\"}})", "{{container}} blocked")], "short", ""),
        ("Loaded classes", [(f"sum by (container) (jvm_classes_loaded_classes{{{C}}}) or sum by (container) (jvm_classes_currently_loaded{{{C}}})", "{{container}}")], "short",
         "Constant growth = classloader leak (redeploys, dynamic proxies)."),
        ("DB connection pool (HikariCP)", [(f"sum by (container, pool) (hikaricp_connections_active{{{C}}})", "{{container}} {{pool}} active"),
                                           (f"sum by (container, pool) (hikaricp_connections_pending{{{C}}})", "{{container}} {{pool}} waiting")], "short",
         "Waiting > 0 = pool too small or slow queries."),
    ]),
    "node": ("Node.js", "prom-client collectDefaultMetrics().", [
        ("Event loop lag", [(f"max by (container) (nodejs_eventloop_lag_p99_seconds{{{C}}})", "{{container}} p99"),
                            (f"max by (container) (nodejs_eventloop_lag_seconds{{{C}}})", "{{container}} current")], "s",
         "How late timers run. Over 100 ms = CPU-bound code blocking the loop; every request waits."),
        ("Heap used / total", [(f"sum by (container) (nodejs_heap_size_used_bytes{{{C}}})", "{{container}} used"),
                               (f"sum by (container) (nodejs_heap_size_total_bytes{{{C}}})", "{{container}} total")], "bytes", ""),
        ("GC time per second", [(f"sum by (container, kind) (rate(nodejs_gc_duration_seconds_sum{{{C}}}[5m]))", "{{container}} {{kind}}")], "percentunit", ""),
        ("Active handles / requests", [(f"sum by (container) (nodejs_active_handles_total{{{C}}})", "{{container}} handles"),
                                       (f"sum by (container) (nodejs_active_requests_total{{{C}}})", "{{container}} requests")], "short",
         "Steady growth = sockets or timers not closed."),
    ]),
    "python": ("Python", "prometheus_client default metrics (gc, process).", [
        ("GC collections/s by generation", [(f"sum by (container, generation) (rate(python_gc_collections_total{{{C}}}[5m]))", "{{container}} gen {{generation}}")], "short",
         "Gen 2 often = many long-lived objects churned."),
        ("Objects collected/s", [(f"sum by (container, generation) (rate(python_gc_objects_collected_total{{{C}}}[5m]))", "{{container}} gen {{generation}}")], "short", ""),
        ("Uncollectable objects", [(f"sum by (container) (python_gc_objects_uncollectable_total{{{C}}})", "{{container}}")], "short",
         "Should stay 0. Growth = reference cycles with __del__ (leak)."),
        ("Resident memory", [(f"sum by (container) (process_resident_memory_bytes{{{C}}})", "{{container}}")], "bytes", ""),
    ]),
    "php": ("PHP", "php-fpm_exporter (hipages) next to PHP-FPM.", [
        ("FPM processes", [(f"sum by (container) (phpfpm_active_processes{{{C}}})", "{{container}} active"),
                           (f"sum by (container) (phpfpm_idle_processes{{{C}}})", "{{container}} idle")], "short", ""),
        ("Listen queue", [(f"sum by (container) (phpfpm_listen_queue{{{C}}})", "{{container}}")], "short",
         "Requests waiting for a free worker. Above 0 = raise pm.max_children."),
        ("Max children reached", [(f"sum by (container) (increase(phpfpm_max_children_reached{{{C}}}[5m]))", "{{container}}")], "short", ""),
        ("Accepted connections/s", [(f"sum by (container) (rate(phpfpm_accepted_connections{{{C}}}[5m]))", "{{container}}")], "reqps", ""),
    ]),
    "dotnet": (".NET", "prometheus-net default metrics.", [
        ("Managed memory", [(f"sum by (container) (dotnet_total_memory_bytes{{{C}}})", "{{container}}")], "bytes", ""),
        ("GC collections/s by generation", [(f"sum by (container, generation) (rate(dotnet_collection_count_total{{{C}}}[5m]))", "{{container}} gen {{generation}}")], "short", ""),
        ("Thread pool", [(f"sum by (container) (dotnet_threadpool_num_threads{{{C}}})", "{{container}} threads"),
                         (f"sum by (container) (dotnet_threadpool_queue_length{{{C}}})", "{{container}} queued")], "short", ""),
        ("Exceptions/s", [(f"sum by (container) (rate(dotnet_exceptions_total{{{C}}}[5m]))", "{{container}}")], "short", ""),
    ]),
    "rust": ("Rust", "Rust has no runtime: process metrics (prometheus crate process feature) and cAdvisor only.", []),
    "ruby": ("Ruby", "prometheus-client / yabeda: process metrics; GC panels when ruby_gc_* is exported.", [
        ("GC runs/s", [(f"sum by (container) (rate(ruby_gc_count{{{C}}}[5m]))", "{{container}}")], "short", ""),
        ("Heap live slots", [(f"sum by (container) (ruby_gc_heap_live_slots{{{C}}})", "{{container}}")], "short", ""),
    ]),
}

for lang, (name, about, panels) in LANGS.items():
    d = Dash(f"runtime-{lang}", f"Runtime: {name}",
             f"{name} runtime of containers labelled container.lang={lang}. {about}",
             ["runtime", lang, "services"], time_from="now-3h", variables=VARS)
    common(d)
    if panels:
        d.row(f"{name} runtime")
        for title, targets, unit, desc in panels:
            p = ts(title, [tgt(e, l) for e, l in targets], unit=unit, desc=desc, fill=10 if unit != "s" else 0)
            p["fieldConfig"]["defaults"]["noValue"] = f"No {name} app exposes these metrics (yet)"
            d.add(p, 12, 8)
    d.write(f"Apps/runtime-{lang}.json")

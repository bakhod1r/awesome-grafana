"""Docker Projects: every running compose project and its services (cAdvisor + Vector logs)."""
from lib import *

UID, SLUG = "docker-projects", "docker-projects"
PJ = "container_label_com_docker_compose_project"
SV = "container_label_com_docker_compose_service"
# container.* labels on the container (docker-compose labels:), exported by cAdvisor as container_label_container_*
LABELS = ("type", "lang", "team", "env")
LSEL = "".join(f', container_label_container_{l}=~"${l}"' for l in LABELS)
SEL = f'name!="", {PJ}=~"$project", {SV}=~"$service"{LSEL}'


def C(metric, extra=""):
    return f"{metric}{{{SEL}{extra}}}"


def short(expr):
    """Long cAdvisor labels → project / service; containers outside compose → (standalone) / container name."""
    e = f'label_replace({expr}, "project", "$1", "{PJ}", "(.+)")'
    e = f'label_replace({e}, "project", "(standalone)", "project", "")'
    if "name" in expr:  # container name first, so the compose service (when set) overwrites it
        e = f'label_replace({e}, "service", "$1", "name", "(.+)")'
    return f'label_replace({e}, "service", "$1", "{SV}", "(.+)")'


def by_p(agg, expr):
    return short(f"{agg} by ({PJ}) ({expr})")


def by_s(agg, expr):
    return short(f"{agg} by ({PJ}, {SV}, name) ({expr})")


def by_svc(agg, expr):
    return short(f"{agg} by ({PJ}, {SV}) ({expr})")


CPU = f'rate({C("container_cpu_usage_seconds_total")}[5m])'
MEM = C("container_memory_working_set_bytes")
RX = f'rate({C("container_network_receive_bytes_total")}[5m])'
TX = f'rate({C("container_network_transmit_bytes_total")}[5m])'
RD = f'rate({C("container_fs_reads_bytes_total")}[5m])'
WR = f'rate({C("container_fs_writes_bytes_total")}[5m])'
LOGSEL = 'project=~"$project", service=~"$service"'
ERRS = f'sum by (project, service) (rate(vector_log_lines_total{{{LOGSEL}, level=~"error|fatal|panic"}}[5m])) * 60'
LOGF = 'project:~"${project:regex}" service:~"${service:regex}"'

PROJECT_LINK = [{"title": "Only this project: ${__data.fields.project}",
                 "url": f"/d/{UID}/{SLUG}?${{__url_time_range}}&var-project=${{__data.fields.project}}"}]
SERVICE_LINK = [{"title": "Only this service", "url": f"/d/{UID}/{SLUG}?${{__url_time_range}}&var-project=${{__data.fields.project}}&var-service=${{__data.fields.service}}"},
                {"title": "Logs of this container", "url": "/d/logs/logs?${__url_time_range}&var-container=${__data.fields.name}"}]

P_PROJ, P_SVC, P_GONE, P_OOM, P_ERRLOG, P_MEM = 901, 902, 903, 904, 905, 906

d = Dash(UID, "Docker Projects",
         "Every running docker compose project and its services: status, uptime, CPU, RAM, network, disk, restarts, OOM, logs. "
         "New projects appear on their own (from cAdvisor docker labels).",
         ["docker", "containers", "projects", "overview", "cadvisor"],
         variables=[
             query_var("project", "Project", f'label_values(container_last_seen{{name!=""}}, {PJ})', desc="docker compose project name (folder name or -p)."),
             query_var("service", "Service", f'label_values(container_last_seen{{name!="", {PJ}=~"$project"}}, {SV})', desc="compose service name."),
         ])

d.row("Health — what runs in Docker")
d.add(text("Click a project name in **Projects** to filter the whole dashboard. "
           "In **Services**: service name = only that service, container name = its logs. "
           "Red = needs attention now: OOM, recently restarted, error logs, RAM near limit."), 24, 2)
d.add(stat("Projects", f'count(count by ({PJ}) (container_last_seen{{name!="", {PJ}=~"$project"}}))', color_mode="value", th=steps(base="blue"),
           link=view(UID, SLUG, P_PROJ, "Projects table"), desc="Compose projects running now."), 3, 4)
d.add(stat("Containers running", f'count(count by (name) ({C("container_last_seen")}))', color_mode="value", th=steps(base="blue"),
           link=view(UID, SLUG, P_SVC, "Services table"), desc="Containers running now."), 3, 4)
d.add(stat("Gone (last 1h)", f'count(time() - max by (name) (max_over_time({C("container_last_seen")}[1h])) > 120) or vector(0)',
           th=steps((1, "red")), link=view(UID, SLUG, P_GONE, "Which ones disappeared?"),
           desc="Containers that ran in the last hour but are gone now (stopped, crashed, removed)."), 3, 4)
d.add(stat("Started (last 1h)", f'count(time() - max by (name) ({C("container_start_time_seconds")}) < 3600) or vector(0)',
           th=steps((1, "yellow"), (5, "red")), link=view(UID, SLUG, P_SVC, "Which ones? (Uptime column)"),
           desc="Containers started or restarted in the last hour. Unexpected = crash loop."), 3, 4)
d.add(stat("OOM kills (range)", f'sum(increase({C("container_oom_events_total")}[$__range])) or vector(0)', th=steps((1, "red")), decimals=0,
           link=view(UID, SLUG, P_OOM, "Which container?"), desc="Processes the kernel killed for lack of memory."), 3, 4)
d.add(stat("CPU (cores)", f'sum({CPU})', unit="none", decimals=2, color_mode="value", th=steps(base="blue"),
           desc="CPU cores used by all selected containers."), 3, 4)
d.add(stat("Memory", f'sum({MEM}) / max(last_over_time(machine_memory_bytes[1h]))', unit="percentunit", th=steps((0.7, "yellow"), (0.85, "red")), decimals=1,
           link=view(UID, SLUG, P_MEM, "Who uses the most RAM?"), desc="Container RAM as a share of Docker host memory."), 3, 4)
d.add(stat("Error logs/min", f'sum(rate(vector_log_lines_total{{{LOGSEL}, level=~"error|fatal|panic"}}[5m])) * 60 or vector(0)',
           th=steps((1, "yellow"), (20, "red")), decimals=1, link=view(UID, SLUG, P_ERRLOG, "Error logs"),
           desc="error/fatal/panic lines in the selected projects' logs, per minute."), 3, 4)

d.row("Projects")
proj = table("Projects overview", [
    tgt(by_p("count", f'count by ({PJ}, name) ({C("container_last_seen")})'), instant=True, fmt="table"),
    tgt(by_p("sum", CPU), instant=True, fmt="table"),
    tgt(by_p("sum", MEM), instant=True, fmt="table"),
    tgt(by_p("sum", MEM) + " / scalar(max(last_over_time(machine_memory_bytes[1h])))", instant=True, fmt="table"),
    tgt(by_p("sum", RX), instant=True, fmt="table"),
    tgt(by_p("sum", TX), instant=True, fmt="table"),
    tgt(by_p("sum", f"{RD} + {WR}"), instant=True, fmt="table"),
    tgt(by_p("count", f'time() - max by ({PJ}, name) ({C("container_start_time_seconds")}) < 3600') + " or " + by_p("count", f'count by ({PJ}, name) ({C("container_last_seen")})') + " * 0", instant=True, fmt="table"),
    tgt(by_p("sum", f'increase({C("container_oom_events_total")}[$__range])'), instant=True, fmt="table"),
    tgt(f'sum by (project) (rate(vector_log_lines_total{{{LOGSEL}, level=~"error|fatal|panic"}}[5m])) * 60', instant=True, fmt="table"),
    tgt(by_p("min", f'time() - {C("container_start_time_seconds")}'), instant=True, fmt="table"),
], desc="One row per compose project. Click a name to filter the dashboard.",
    sort=("CPU", True), hide=(PJ,),
    rename={"Value #A": "Containers", "Value #B": "CPU", "Value #C": "Memory", "Value #D": "RAM % host", "Value #E": "Net in",
            "Value #F": "Net out", "Value #G": "Disk IO", "Value #H": "Started <1h", "Value #I": "OOM", "Value #J": "Errors/min", "Value #K": "Youngest uptime"},
    order=["project"],
    overrides=[col("project", links=PROJECT_LINK, width=200), col("CPU", unit="none", decimals=2, cell=BAR, th=steps((1, "yellow"), (2, "red"))),
               col("Memory", unit="bytes", decimals=1), col("RAM % host", unit="percentunit", cell=GAUGE, th=steps((0.5, "yellow"), (0.8, "red")), minv=0, maxv=1),
               col("Net in", unit="Bps"), col("Net out", unit="Bps"), col("Disk IO", unit="Bps"),
               col("Started <1h", cell=BG, th=steps((1, "yellow"), (3, "red")), decimals=0), col("OOM", cell=BG, th=steps((1, "red")), decimals=0),
               col("Errors/min", cell=BG, th=steps((1, "yellow"), (20, "red")), decimals=1), col("Youngest uptime", unit="s", decimals=0)])
proj["id"] = P_PROJ
d.add(proj, 24, 7)
d.add(ts("CPU by project", [tgt(by_p("sum", CPU), "{{project}}")], unit="none", stack=True, desc="CPU cores by project."), 8, 8)
d.add(ts("Memory by project", [tgt(by_p("sum", MEM), "{{project}}")], unit="bytes", stack=True, desc="Working set (the memory the OOM killer sees)."), 8, 8)
d.add(ts("Network by project", [tgt(by_p("sum", RX), "{{project}} in"), tgt(by_p("sum", TX) + " * -1", "{{project}} out")], unit="Bps",
         desc="Yuqori = kirgan, past = chiqqan trafik."), 8, 8)

d.row("Services — inside the project")
svc = table("Services", [
    tgt(by_s("max", f'time() - {C("container_start_time_seconds")}'), instant=True, fmt="table"),
    tgt(by_s("max", C("container_health_state")), instant=True, fmt="table"),
    tgt(by_s("sum", CPU), instant=True, fmt="table"),
    tgt(by_s("sum", MEM), instant=True, fmt="table"),
    tgt(by_s("sum", MEM) + " / " + by_s("max", C("container_spec_memory_limit_bytes") + " > 0"), instant=True, fmt="table"),
    tgt(by_s("sum", RX), instant=True, fmt="table"),
    tgt(by_s("sum", TX), instant=True, fmt="table"),
    tgt(by_s("sum", RD), instant=True, fmt="table"),
    tgt(by_s("sum", WR), instant=True, fmt="table"),
    tgt(by_s("sum", f'rate({C("container_pressure_cpu_waiting_seconds_total")}[5m])'), instant=True, fmt="table"),
    tgt(by_s("sum", f'increase({C("container_oom_events_total")}[$__range])'), instant=True, fmt="table"),
    tgt(f'sum by (project, service) (rate(vector_log_lines_total{{{LOGSEL}, level=~"error|fatal|panic"}}[5m])) * 60', instant=True, fmt="table"),
], desc="Every container: uptime, healthcheck, resources, errors. Red uptime = recently restarted. "
        "RAM % limit only for containers with mem_limit. CPU wait = time queued for CPU (PSI): high = not enough CPU.",
    sort=("CPU", True), hide=(PJ, SV),
    rename={"Value #A": "Uptime", "Value #B": "Health", "Value #C": "CPU", "Value #D": "Memory", "Value #E": "RAM % limit",
            "Value #F": "Net in", "Value #G": "Net out", "Value #H": "Disk read", "Value #I": "Disk write", "Value #J": "CPU wait",
            "Value #K": "OOM", "Value #L": "Errors/min"},
    order=["project", "service", "name"],
    overrides=[col("service", links=SERVICE_LINK, width=170), col("project", width=140), col("name", width=230, links=SERVICE_LINK[1:]),
               col("Uptime", unit="s", cell=TXT, th=steps((600, "yellow"), (3600, "green"), base="red"), decimals=0),
               col("Health", cell=BG, mappings=vmap({"1": ("healthy", "green"), "0": ("unhealthy", "red"), "-1": ("no check", "transparent")})),
               col("CPU", unit="none", decimals=3, cell=BAR, th=steps((0.5, "yellow"), (1, "red"))),
               col("Memory", unit="bytes", decimals=1), col("RAM % limit", unit="percentunit", cell=GAUGE, th=steps((0.7, "yellow"), (0.9, "red")), minv=0, maxv=1),
               col("Net in", unit="Bps"), col("Net out", unit="Bps"), col("Disk read", unit="Bps"), col("Disk write", unit="Bps"),
               col("CPU wait", unit="percentunit", cell=TXT, th=steps((0.1, "yellow"), (0.3, "red")), decimals=1),
               col("OOM", cell=BG, th=steps((1, "red")), decimals=0), col("Errors/min", cell=BG, th=steps((1, "yellow"), (20, "red")), decimals=1)])
svc["id"] = P_SVC
d.add(svc, 24, 10)
d.add(state_timeline("Container presence (up / gone)", [tgt(by_s("count", C("container_last_seen")), "{{project}} / {{service}}")],
                     desc="When each container was running. Gap = stopped or gone, break in colour = restarted.",
                     th=steps(base="green"), mappings=vmap({"1": ("up", "green")})), 24, 8)
gone = table("Gone in the last hour", [
    tgt(by_s("max", f'time() - max_over_time({C("container_last_seen")}[1h])') + " > 120", instant=True, fmt="table")],
    desc="Containers seen in the last hour that are gone now, and how long ago they disappeared.",
    hide=(PJ, SV), rename={"Value": "Gone for"}, order=["project", "service", "name"], merge=False,
    overrides=[col("Gone for", unit="s", cell=BG, th=steps(base="red"), decimals=0)])
gone["id"] = P_GONE
d.add(gone, 8, 7)
d.add(ts("Uptime by container", [tgt(by_s("max", f'time() - {C("container_start_time_seconds")}'), "{{service}}")], unit="s", fill=0, legend="hidden",
         desc="Sawtooth = repeated restarts (crash loop)."), 16, 7)

d.row("Resources by service")
d.add(ts("CPU by service", [tgt(by_svc("sum", CPU), "{{project}}/{{service}}")], unit="none", stack=True, desc="CPU cores."), 12, 8)
mem = ts("Memory by service", [tgt(by_svc("sum", MEM), "{{project}}/{{service}}")], unit="bytes", stack=True, desc="Working set. Constant growth = memory leak.")
mem["id"] = P_MEM
d.add(mem, 12, 8)
d.add(ts("Network in by service", [tgt(by_svc("sum", RX), "{{project}}/{{service}}")], unit="Bps", stack=True), 12, 8)
d.add(ts("Network out by service", [tgt(by_svc("sum", TX), "{{project}}/{{service}}")], unit="Bps", stack=True), 12, 8)
d.add(ts("Disk read by service", [tgt(by_svc("sum", RD), "{{project}}/{{service}}")], unit="Bps", stack=True), 12, 8)
d.add(ts("Disk write by service", [tgt(by_svc("sum", WR), "{{project}}/{{service}}")], unit="Bps", stack=True), 12, 8)
d.add(bargauge("Top memory", [tgt(f"topk(10, {by_s('sum', MEM)})", "{{project}}/{{service}}", instant=True)], unit="bytes",
               th=steps((536870912, "yellow"), (1073741824, "red")), desc="10 containers using the most RAM."), 8, 8)
d.add(bargauge("Top CPU", [tgt(f"topk(10, {by_s('sum', CPU)})", "{{project}}/{{service}}", instant=True)], unit="none",
               th=steps((0.5, "yellow"), (1, "red")), desc="10 containers using the most CPU."), 8, 8)
d.add(piechart("Memory share by project", [tgt(by_p("sum", MEM), "{{project}}", instant=True)], unit="bytes", desc="How RAM is split between projects."), 8, 8)

d.row("Pressure, network errors, OOM", collapsed=True)
d.add(ts("CPU pressure (waiting)", [tgt(by_svc("sum", f'rate({C("container_pressure_cpu_waiting_seconds_total")}[5m])'), "{{project}}/{{service}}")], unit="percentunit",
         th=steps((0.1, "yellow"), (0.3, "red")), fill=0, desc="Share of time processes waited for CPU (PSI). High = CPU shortage, latency grows."), 8, 8)
d.add(ts("Memory pressure (stalled)", [tgt(by_svc("sum", f'rate({C("container_pressure_memory_stalled_seconds_total")}[5m])'), "{{project}}/{{service}}")], unit="percentunit",
         th=steps((0.05, "yellow"), (0.2, "red")), fill=0, desc="Time stalled waiting for memory reclaim. Above 0 = RAM shortage."), 8, 8)
d.add(ts("IO pressure (stalled)", [tgt(by_svc("sum", f'rate({C("container_pressure_io_stalled_seconds_total")}[5m])'), "{{project}}/{{service}}")], unit="percentunit",
         th=steps((0.1, "yellow"), (0.3, "red")), fill=0, desc="Time stalled waiting for disk."), 8, 8)
oom = ts("OOM kills", [tgt(by_s("sum", f'increase({C("container_oom_events_total")}[5m])') + " > 0", "{{project}}/{{service}}")], draw="bars", fill=80,
         desc="Processes killed for lack of memory. Raise mem_limit or look for a leak.")
oom["id"] = P_OOM
d.add(oom, 8, 8)
d.add(ts("Network errors & drops", [tgt(by_svc("sum", f'rate({C("container_network_receive_errors_total")}[5m]) + rate({C("container_network_transmit_errors_total")}[5m])'), "{{project}}/{{service}} errors"),
                                    tgt(by_svc("sum", f'rate({C("container_network_receive_packets_dropped_total")}[5m]) + rate({C("container_network_transmit_packets_dropped_total")}[5m])'), "{{project}}/{{service}} drops")],
         unit="pps", fill=0, desc="Normally 0."), 8, 8)
d.add(ts("Memory: RSS vs cache", [tgt(by_svc("sum", C("container_memory_rss")), "{{project}}/{{service}} rss"),
                                  tgt(by_svc("sum", C("container_memory_cache")), "{{project}}/{{service}} cache")], unit="bytes", fill=0,
         desc="RSS = real process memory, cache = file cache (reclaimable)."), 8, 8)

d.row("Logs")
d.add(vl_ts("Log lines by service", LOGF + ' | stats by (service) count()', "{{service}}", desc="Log volume per service."), 12, 7)
d.add(vl_ts("Errors by service", LOGF + ' level:(error OR fatal OR panic) | stats by (service) count()', "{{service}}", desc="Error logs by service."), 12, 7)
el = logs("Errors & warnings", LOGF + ' level:(error OR fatal OR panic OR warn) | sort by (_time desc) | limit 500',
          desc="error, fatal, panic, warn lines of the selected projects/services.")
el["id"] = P_ERRLOG
d.add(el, 14, 11)
d.add(vl_table("Top error messages", LOGF + ' level:(error OR fatal OR panic) | unpack_logfmt fields (msg, err, error) keep_original_fields | format if (msg:"") "<_msg>" as msg | stats by (service, msg, err, error) count() hits | sort by (hits desc) | limit 20',
               desc="Most repeated errors.", overrides=[col("_msg", width=420), col("hits", cell=BG, th=steps((10, "yellow"), (100, "red")))]), 10, 11)

d.write("Infra/docker-projects.json")

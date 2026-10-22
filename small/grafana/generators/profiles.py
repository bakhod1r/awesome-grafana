"""Profiles: continuous profiling from Pyroscope — CPU and memory flame graphs per service, plus profile time series."""
from lib import *

UID, SLUG = "profiles", "profiles"
PYRO = {"type": "grafana-pyroscope-datasource", "uid": "pyroscope"}
CPU = "process_cpu:cpu:nanoseconds:cpu:nanoseconds"
ALLOC = "memory:alloc_space:bytes:space:bytes"
INUSE = "memory:inuse_space:bytes:space:bytes"
GOR = "goroutine:goroutine:count:goroutine:count"
SEL = '{service_name=~"$service"}'


def ptgt(ptype, query_type="profile", group_by=()):
    return {"refId": "A", "datasource": PYRO, "queryType": query_type, "profileTypeId": ptype, "labelSelector": SEL,
            "groupBy": list(group_by), "spanSelector": []}


def flame(title, ptype, desc=""):
    return {"type": "flamegraph", "title": title, "description": desc, "datasource": PYRO, "targets": [ptgt(ptype)], "options": {}}


def pts(title, ptype, unit, desc=""):
    p = ts(title, [], unit=unit, desc=desc, fill=0, ds=PYRO)
    p["targets"] = [ptgt(ptype, "metrics", ["service_name"])]
    p["targets"][0]["legendFormat"] = "{{service_name}}"
    return p


svc_var = {"name": "service", "label": "Service", "type": "query", "datasource": PYRO,
           "query": {"type": "labelValue", "labelName": "service_name", "profileTypeId": CPU, "refId": "service"},
           "refresh": 2, "includeAll": False, "multi": False, "sort": 1,
           "description": "service_name in Pyroscope. Stack services are pulled by Alloy (alloy/config.alloy)."}

d = Dash(UID, "Profiles",
         "Continuous profiling (Pyroscope): where each service spends CPU and memory, down to the function. "
         "Pick a service; compare time ranges to find what changed after a deploy. From a trace in Tempo, 'Profiles for this span' opens the same view.",
         ["profiles", "pyroscope", "performance", "cpu", "memory"], time_from="now-1h", variables=[svc_var],
         links=[{"title": "Explore profiles", "type": "link", "icon": "external link", "url": "/a/grafana-pyroscope-app/explore", "targetBlank": False}])

d.row("Over time")
d.add(pts("CPU time per second", CPU, "ns", desc="CPU nanoseconds per second spent by the service (1e9 = one full core)."), 8, 7)
d.add(pts("Memory in use", INUSE, "bytes", desc="Heap in use at each sample (Go: inuse_space)."), 8, 7)
d.add(pts("Goroutines", GOR, "short", desc="Goroutine count. A line that only goes up is a goroutine leak."), 8, 7)

d.row("Flame graphs — wider bar = more cost; click a frame to zoom")
d.add(flame("CPU", CPU, desc="Total CPU time per function over the selected range. Look for wide bars near the bottom: that code runs most."), 24, 14)
d.add(flame("Memory allocations", ALLOC, desc="Bytes allocated per function. Heavy allocators drive GC CPU time."), 12, 14)
d.add(flame("Memory in use", INUSE, desc="Live heap per function at the end of the range: where memory is held."), 12, 14)

d.write("Observability/profiles.json")

"""Rebuild every generated dashboard, then add the shared event annotations to the hand-written ones.

    python3 grafana/generators/build.py

Generators are the other *.py files in this folder (each writes one JSON under grafana/dashboards/).
Hand-written dashboards keep their own annotations; the shared ones from lib.EVENT_ANNOTATIONS are
added or refreshed by name, so container restarts and deploys show on every graph, and the top
navigation (lib.NAV) is refreshed on every dashboard that has it.
"""
import glob
import json
import os
import re
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lib import EVENT_ANNOTATIONS, NAV, ROOT, VL_TABLE_TRANSFORMS, nav_links, widen_graphs  # noqa: E402

# Generators whose JSON was later extended by hand in Grafana: running them would drop those panels.
# docker_projects.py lacks the "Containers (all running)" table and the "Container: $container" row
# that Infra/docker-projects.json has. Port them into the generator, then remove it from this set.
HAND_EDITED = {"docker_projects.py"}

for f in sorted(glob.glob(os.path.join(HERE, "*.py"))):
    if os.path.basename(f) in ("lib.py", "build.py") or os.path.basename(f) in HAND_EDITED:
        continue
    runpy.run_path(f, run_name="__main__")

for f in sorted(glob.glob(os.path.join(ROOT, "**", "*.json"), recursive=True)):
    with open(f) as fh:
        d = json.load(fh)
    layout_before = json.dumps(d.get("panels", [])) + json.dumps(d.get("templating", {}))
    widen_graphs(d)
    # Query variables: a stale URL value (gone container, renamed service) falls back to the default
    # instead of filtering every panel down to "No data".
    for v in d.get("templating", {}).get("list", []):
        if v.get("type") == "query":
            v["allowCustomValue"] = False
    # VictoriaLogs stats tables: one merged table instead of a frame picker (see VL_TABLE_TRANSFORMS).
    for r in d.get("panels", []):
        for p in [r] + r.get("panels", []):
            if p.get("type") == "table" and any(t.get("queryType") == "stats" and "logs" in str((t.get("datasource") or p.get("datasource") or {}).get("type", ""))
                                                for t in p.get("targets", [])):
                tr = p.get("transformations") or []
                if not any(t["id"] == "labelsToFields" for t in tr):
                    org = next((t["options"] for t in tr if t["id"] == "organize"), None)
                    p["transformations"] = VL_TABLE_TRANSFORMS(org)
    # Stat panels: a long "no data" note is shrunk to unreadable text. Keep it short; the full note goes to
    # the (i) description.
    for r in d.get("panels", []):
        for p in [r] + r.get("panels", []):
            dflt = p.get("fieldConfig", {}).get("defaults", {})
            note = dflt.get("noValue", "")
            if p.get("type") == "table" and len(note) > 1:  # a table repeats it in every empty cell
                dflt["noValue"] = "-"
                if note not in p.get("description", ""):
                    p["description"] = (p.get("description", "") + " Empty: " + note).strip()
            if p.get("type") == "stat" and len(note) > 28:
                dflt["noValue"] = "No data"
                if note not in p.get("description", ""):
                    p["description"] = (p.get("description", "") + " Empty: " + note).strip()
    # Graph legends like {{job}}: a series without that label shows as "Value". Name it "(none)" instead.
    for r in d.get("panels", []):
        for p in [r] + r.get("panels", []):
            if p.get("type") != "timeseries":
                continue
            for t in p.get("targets", []):
                ds = str((t.get("datasource") or p.get("datasource") or {}).get("type", ""))
                m = re.fullmatch(r"\{\{\s*(\w+)\s*\}\}", t.get("legendFormat", ""))
                if m and "logs" not in ds and "tempo" not in ds and t.get("expr") and not t["expr"].startswith("label_replace("):
                    t["expr"] = f'label_replace({t["expr"]}, "{m[1]}", "(none)", "{m[1]}", "")'
    relaid = json.dumps(d.get("panels", [])) + json.dumps(d.get("templating", {})) != layout_before
    lst = d.setdefault("annotations", {}).setdefault("list", [])
    before = json.dumps(lst)
    by_name = {a["name"]: a for a in EVENT_ANNOTATIONS}
    lst[:] = [by_name.get(a.get("name"), a) for a in lst]  # refresh in place, keep order
    have = {a.get("name") for a in lst}
    lst.extend(a for a in EVENT_ANNOTATIONS if a["name"] not in have)
    # Top navigation: same links on every dashboard, so a new entry in lib.NAV shows everywhere.
    links = d.setdefault("links", [])
    nav_titles = {t for t, *_ in NAV}
    before += json.dumps(links)
    links[:] = [l for l in links if l.get("title") not in nav_titles] + nav_links(d.get("uid"))
    lst_and_links = json.dumps(lst) + json.dumps(links)
    if lst_and_links != before or relaid:
        with open(f, "w") as fh:
            json.dump(d, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        print(f"{os.path.relpath(f, ROOT)}: shared annotations / navigation / graph widths updated")

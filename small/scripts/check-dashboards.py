#!/usr/bin/env python3
"""Run every panel query of every dashboard through Grafana and list panels that error or show "No data".

    python3 scripts/check-dashboards.py                     # all dashboards, against http://localhost:3000
    python3 scripts/check-dashboards.py --dashboard redis   # one dashboard (uid)
    python3 scripts/check-dashboards.py --all               # also print the panels that are fine

Queries go through Grafana's /api/ds/query, exactly like the browser, so every datasource is covered
(VictoriaMetrics, Prometheus, VictoriaLogs, Tempo, Alertmanager). Dashboard variables are
replaced with "match everything" (.*), or with their current value when they are not query variables.

Panels that set a "No value" text (fieldConfig.defaults.noValue) are expected to be empty sometimes,
e.g. "Replication lag" on a primary: they are listed as EMPTY-OK and do not fail the run.
Exit code: 0 = no errors and no unexpected "No data", 1 otherwise. Login: GRAFANA_ADMIN_USER /
GRAFANA_ADMIN_PASSWORD from the environment or .env (defaults admin/admin).
"""
import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
# Grafana runs these Tempo query types in the browser; /api/ds/query refuses them.
BROWSER_ONLY_TEMPO = {"traceql", "traceqlSearch", "nativeSearch", "search", "serviceMap"}
SKIP_TYPES = {"row", "text", "dashlist", "alertlist", "news", "annolist", "welcome", "gettingstarted"}


def dotenv():
    env = {}
    try:
        with open(os.path.join(ROOT, ".env")) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return env


class Grafana:
    def __init__(self, url, user, password):
        self.url = url.rstrip("/")
        self.auth = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()

    def call(self, path, body=None):
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": self.auth, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            try:
                return json.load(e)
            except ValueError:
                return {"message": f"HTTP {e.code}"}


def var_values(dash):
    """name → replacement. Query variables match everything; others keep their current/default value."""
    out = {}
    for v in dash.get("templating", {}).get("list", []):
        name = v.get("name")
        cur = (v.get("current") or {}).get("value")
        if isinstance(cur, list):
            cur = cur[0] if cur else None
        if v.get("type") == "textbox":  # free text: what the box holds (usually empty)
            out[name] = str(cur if cur is not None else v.get("query", ""))
        elif v.get("type") in ("query", "datasource") or cur in (None, "", "$__all"):
            out[name] = ".*"
        else:
            out[name] = str(cur)
    return out


def interpolate(obj, values):
    """Replace $var, ${var}, ${var:fmt} in every string of a query. Exact matches (="$x") become regex matches."""
    if isinstance(obj, dict):
        return {k: interpolate(v, values) for k, v in obj.items()}
    if isinstance(obj, list):
        return [interpolate(v, values) for v in obj]
    if not isinstance(obj, str):
        return obj
    s = obj
    for name, val in values.items():
        if val == ".*":
            s = re.sub(r'(\w)\s*=\s*"\$\{?' + re.escape(name) + r'(:\w+)?\}?"', r'\1=~".*"', s)  # label="$x" → label=~".*"
            s = re.sub(r'(\w)\s*:=\s*"\$\{?' + re.escape(name) + r'(:\w+)?\}?"', r'\1:~".*"', s)  # LogsQL field:="$x"
        s = re.sub(r"\$\{" + re.escape(name) + r"(:[\w]+)?\}", lambda m: val, s)
        s = re.sub(r"\$" + re.escape(name) + r"\b", lambda m: val, s)
    return s


def has_data(result):
    for fr in result.get("frames", []):
        fields = fr.get("schema", {}).get("fields", [])
        values = fr.get("data", {}).get("values", [])
        for f, vals in zip(fields, values):
            if f.get("type") == "time":
                continue
            if any(v is not None and v != "" for v in vals or []):
                return True
        # a frame with only a time field (e.g. annotations) or no rows counts as empty
    return False


def panels_of(dash):
    for p in dash.get("panels", []):
        yield p
        yield from p.get("panels", [])


def check_panel(g, dash, p, values, time_from):
    ds = p.get("datasource")
    queries = []
    for i, t in enumerate(p.get("targets", [])):
        if t.get("hide"):
            continue
        q = interpolate(t, values)
        q["refId"] = q.get("refId") or chr(65 + i)  # the browser fills in missing refIds the same way
        q["datasource"] = q.get("datasource") or ds
        if not q.get("datasource") or str((q["datasource"] or {}).get("uid", "")).startswith(("-- ", "$")):
            continue
        if (q["datasource"] or {}).get("type") == "tempo" and q.get("queryType") in BROWSER_ONLY_TEMPO:
            return "SKIPPED", "Tempo search / service map run in the browser only, open the dashboard to check"
        q.setdefault("intervalMs", 60000)
        q.setdefault("maxDataPoints", 300)
        queries.append(q)
    if not queries:
        return None, ""
    res = g.call("/api/ds/query", {"queries": queries, "from": time_from, "to": "now"})
    if "results" not in res:
        return "ERROR", res.get("message", "no results")[:160]
    errors = [f'{ref}: {r["error"][:140]}' for ref, r in res["results"].items() if r.get("error")]
    if errors:
        return "ERROR", "; ".join(errors)
    if any(has_data(r) for r in res["results"].values()):
        return "OK", ""
    if (p.get("fieldConfig", {}).get("defaults", {}) or {}).get("noValue"):
        return "EMPTY-OK", p["fieldConfig"]["defaults"]["noValue"][:80]
    return "NO DATA", ""


def main():
    env = {**dotenv(), **os.environ}
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--url", default=env.get("GRAFANA_CHECK_URL", f"http://localhost:{env.get('GRAFANA_PORT', '3000')}"))
    ap.add_argument("--user", default=env.get("GRAFANA_ADMIN_USER", "admin"))
    ap.add_argument("--password", default=env.get("GRAFANA_ADMIN_PASSWORD", "admin"))
    ap.add_argument("--dashboard", action="append", help="dashboard uid (repeatable); default: all")
    ap.add_argument("--from", dest="time_from", help="time range start, e.g. now-1h (default: each dashboard's own)")
    ap.add_argument("--all", action="store_true", help="also list panels that are fine")
    a = ap.parse_args()

    g = Grafana(a.url, a.user, a.password)
    found = g.call("/api/search?type=dash-db&limit=5000")
    if not isinstance(found, list):
        sys.exit(f"Cannot list dashboards at {a.url}: {found.get('message')}")
    uids = [d["uid"] for d in found if not a.dashboard or d["uid"] in a.dashboard]

    counts = {"OK": 0, "EMPTY-OK": 0, "SKIPPED": 0, "NO DATA": 0, "ERROR": 0}
    for uid in sorted(uids):
        dash = g.call(f"/api/dashboards/uid/{uid}")["dashboard"]
        values = var_values(dash)
        tf = a.time_from or dash.get("time", {}).get("from", "now-6h")
        lines = []
        for p in panels_of(dash):
            if p.get("type") in SKIP_TYPES:
                continue
            status, detail = check_panel(g, dash, p, values, tf)
            if status is None:
                continue
            counts[status] += 1
            if status != "OK" or a.all:
                lines.append(f"  {status:<9} {p.get('title') or '(no title)'}" + (f"  — {detail}" if detail else ""))
        print(f"{dash['title']} ({uid})" + ("" if lines else "  all panels have data"))
        print("\n".join(lines)) if lines else None

    print(f"\n{counts['OK']} OK, {counts['EMPTY-OK']} empty but expected, {counts['SKIPPED']} skipped, "
          f"{counts['NO DATA']} no data, {counts['ERROR']} errors")
    sys.exit(1 if counts["NO DATA"] or counts["ERROR"] else 0)


if __name__ == "__main__":
    main()

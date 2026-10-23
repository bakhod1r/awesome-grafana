"""Finds every container on this Docker host that serves Prometheus metrics and tells Prometheus.

Every SCAN_INTERVAL seconds:
  1. list running containers (Docker API over /var/run/docker.sock)
  2. for each new container: connect this container, Prometheus and blackbox to its network,
     then try GET /metrics on its exposed ports and on a few common metrics ports
  3. write every container that answered in Prometheus text format to TARGETS_FILE (file_sd JSON)
Prometheus re-reads that file every 30s (job "apps"), so new projects appear without any edit.
Stopped containers drop out of the file on the next scan, so they never cause TargetDown.

Per-container overrides (labels on the container, all optional):
  prometheus.scrape:  "false"   never scrape this container
  prometheus.port:    "1234"    metrics are on this port (skip probing)
  prometheus.path:    "/stats"  metrics path (default /metrics)
  prometheus.service: "name"    service label (default <project>-<compose service>)
  container.project:  "name"    project label (default: the compose project)
"""

import http.client
import json
import os
import re
import socket
import sys
import time
import urllib.parse
import urllib.request

SOCKET = "/var/run/docker.sock"
TARGETS_FILE = os.environ.get("TARGETS_FILE", "/targets/auto.json")
SCAN_INTERVAL = int(os.environ.get("SCAN_INTERVAL", "15"))
RETRY_AFTER = int(os.environ.get("RETRY_AFTER", "300"))  # re-probe containers without metrics this often
COMMON_PORTS = [int(p) for p in os.environ.get("COMMON_PORTS", "9090,9100,8080,2112,9464,8000,3000").split(",")]
SELF_PROJECT = os.environ.get("SELF_PROJECT", "")  # our own compose project: scraped by static jobs
# Our containers that must follow every app network: Prometheus scrapes, blackbox probes.
JOINERS = os.environ.get("JOINERS", "prometheus,blackbox-exporter,discoverer").split(",")
SITES_FILE = os.environ.get("SITES_FILE", "/targets/sites.json")  # blackbox-http targets from SITES_* (.env)
SITES_PROJECT = os.environ.get("SITES_PROJECT", "")  # project label on those sites
# Targets that depend on .env, written once at start (same volume as TARGETS_FILE), so nothing
# server-specific lives in the repo: an unset variable means no target and no TargetDown.
POSTGRES_FILE = os.environ.get("POSTGRES_FILE", "/targets/postgres.json")
MINIO_FILE = os.environ.get("MINIO_FILE", "/targets/minio.json")
BEYLA_FILE = os.environ.get("BEYLA_FILE", "/targets/beyla.yml")
METRICS_RE = re.compile(rb"^# (TYPE|HELP) [a-zA-Z_:][a-zA-Z0-9_:]* ", re.M)


class UnixConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(SOCKET)


def docker(method, path, body=None):
    c = UnixConnection("docker", timeout=10)
    c.request(method, path, json.dumps(body) if body is not None else None,
              {"Content-Type": "application/json"})
    r = c.getresponse()
    data = r.read()
    c.close()
    if r.status >= 400 and r.status != 403:  # 403 on network connect = already connected
        raise RuntimeError(f"{method} {path}: {r.status} {data[:200]!r}")
    return json.loads(data) if r.headers.get("Content-Type", "").startswith("application/json") and data else None


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def looks_like_metrics(host, port, path):
    try:
        with urllib.request.urlopen(f"http://{host}:{port}{path}", timeout=2) as r:
            return r.status == 200 and bool(METRICS_RE.search(r.read(65536)))
    except Exception:
        return False


def own_containers():
    flt = json.dumps({"label": [f"com.docker.compose.project={SELF_PROJECT}"]})
    return {c["Labels"].get("com.docker.compose.service"): c["Id"]
            for c in docker("GET", "/containers/json?filters=" + urllib.parse.quote(flt))
            if c["Labels"].get("com.docker.compose.service") in JOINERS}


def write_sites():
    """Sites to probe from .env: SITES_PROD=https://a,https://b becomes targets with env="prod"
    (any SITES_<ENV> variable; commas or spaces between URLs). Written once at start.
    An item may be service=url: the service label ties the probe to that container's dashboards
    (Frontend uptime / SSL), e.g. SITES_DEV=dev_admin=https://dev.admin.example.com/"""
    groups = []
    for key, value in sorted(os.environ.items()):
        if not key.startswith("SITES_") or key in ("SITES_FILE", "SITES_PROJECT"):
            continue
        for item in (u for u in re.split(r"[,\s]+", value) if u):
            service, _, url = item.rpartition("=") if "=" in item.split("://")[0] else ("", "", item)
            labels = {"env": key[len("SITES_"):].lower(), "module": "http_alive"}  # up unless 5xx/timeout
            if SITES_PROJECT:
                labels["project"] = SITES_PROJECT
            if service:
                labels["service"] = service
            groups.append({"targets": [url], "labels": labels})
    with open(SITES_FILE + ".tmp", "w") as f:
        json.dump(groups, f, indent=2)
    os.replace(SITES_FILE + ".tmp", SITES_FILE)
    log("wrote", sum(len(g["targets"]) for g in groups), "sites from .env")


def write_json(path, data):
    with open(path + ".tmp", "w") as f:
        json.dump(data, f, indent=2)
    os.replace(path + ".tmp", path)


def write_env_targets():
    """postgres.json: one target per DSN in POSTGRES_EXPORTER_DSN (comma-separated, at most two;
    the exporters listen on the Docker bridge, ports 39187 and 39188, see docker-compose.yml).
    minio.json: MINIO_ENDPOINT:MINIO_PORT, https when MINIO_USE_SSL=true."""
    dsns = [d for d in os.environ.get("POSTGRES_EXPORTER_DSN", "").split(",") if d.strip()][:2]
    names = ["docker", "server"]  # instance label = name in the PostgreSQL dashboard's Server picker
    write_json(POSTGRES_FILE, [{"targets": [f"host.docker.internal:{39187 + i}"], "labels": {"instance": names[i]}}
                               for i in range(len(dsns))])
    endpoint = os.environ.get("MINIO_ENDPOINT", "")
    minio = []
    if endpoint:
        labels = {"instance": "minio"}
        if os.environ.get("MINIO_USE_SSL", "false").lower() == "true":
            labels["__scheme__"] = "https"
        minio.append({"targets": [f'{endpoint}:{os.environ.get("MINIO_PORT", "9000")}'], "labels": labels})
    write_json(MINIO_FILE, minio)
    log("wrote", len(dsns), "postgres and", len(minio), "minio targets from .env")


def write_beyla_config():
    """Beyla config from BEYLA_SERVICES: name=port, or name=exe:port when several processes share
    the port (e.g. frontend_nginx=nginx:80); commas between entries. Beyla starts after this file exists."""
    services = []
    for item in (s for s in re.split(r"[,\s]+", os.environ.get("BEYLA_SERVICES", "")) if s):
        name, _, spec = item.partition("=")
        exe, _, port = spec.rpartition(":")
        svc = {"name": name, "open_ports": port}
        if exe:
            svc["exe_path"] = exe
        services.append(svc)
    cfg = {
        # JSON is valid YAML. Same settings as beyla/beyla.yml (documented there), plus the services.
        "discovery": {"services": services,
                      # Docker publishes ports through dockerd/docker-proxy: they also "own" the port.
                      "exclude_services": [{"exe_path": "dockerd|docker-proxy|containerd"}]},
        "routes": {"unmatched": "heuristic"},
        "prometheus_export": {"port": 9400, "path": "/metrics", "features": ["application"]},
        "otel_traces_export": {"endpoint": "http://vector:4317", "protocol": "grpc"},
    }
    write_json(BEYLA_FILE, cfg)
    log("wrote beyla config with", len(services), "services")


def main():
    if not SELF_PROJECT:
        sys.exit("SELF_PROJECT is not set")
    write_sites()
    write_env_targets()
    write_beyla_config()
    found = {}      # container id -> file_sd entry, or None = no metrics found
    checked = {}    # container id -> time of last probe
    joined = set()  # (network id, our container id) pairs already connected
    last_own, last_written = set(), None
    while True:
        try:
            own = own_containers()
            # Prometheus/blackbox recreated (new id): it lost every app network. Start over.
            if set(own.values()) != last_own:
                found.clear(); checked.clear(); joined.clear()
                last_own = set(own.values())
            alive = set()
            for c in docker("GET", "/containers/json"):
                cid, labels = c["Id"], c.get("Labels") or {}
                alive.add(cid)
                project = labels.get("container.project") or labels.get("com.docker.compose.project", "")
                if project == SELF_PROJECT or labels.get("prometheus.scrape") == "false":
                    continue
                # Static frontends (nginx serving a JS bundle) have no /metrics: probing them only adds
                # "/metrics" 404 lines to their access log and the Frontend dashboard. Opt in with prometheus.port.
                if labels.get("container.type") == "frontend" and "prometheus.port" not in labels:
                    continue
                if cid in found and (found[cid] or time.time() - checked[cid] < RETRY_AFTER):
                    continue
                name = c["Names"][0].lstrip("/")
                nets = {n: v for n, v in ((c.get("NetworkSettings") or {}).get("Networks") or {}).items() if n not in ("host", "none")}
                checked[cid], found[cid] = time.time(), None
                if not nets:
                    continue
                net, info = next(iter(nets.items()))
                missing = [oid for oid in own.values() if (info["NetworkID"], oid) not in joined]
                for oid in missing:
                    docker("POST", f"/networks/{net}/connect", {"Container": oid})
                    joined.add((info["NetworkID"], oid))
                if missing:
                    log("joined network", net)
                # Container names resolve on user networks; the default bridge only has IPs.
                host = name if net != "bridge" else info["IPAddress"]
                path = labels.get("prometheus.path", "/metrics")
                if labels.get("prometheus.port"):
                    ports = [int(labels["prometheus.port"])]
                else:
                    exposed = [p["PrivatePort"] for p in c.get("Ports") or [] if p.get("Type") == "tcp"]
                    ports = list(dict.fromkeys(exposed + COMMON_PORTS))
                port = next((p for p in ports if looks_like_metrics(host, p, path)), None)
                if port is None:
                    continue
                service = labels.get("com.docker.compose.service", "")
                found[cid] = {"targets": [f"{host}:{port}"], "labels": {
                    "service": labels.get("prometheus.service", f"{project}-{service}" if project else name),
                    "project": project or "(standalone)", "container": name,
                    "__metrics_path__": path, "discovered": "auto"}}
                log("found", name, f"{host}:{port}{path}", "service=" + found[cid]["labels"]["service"])
            for cid in [k for k in found if k not in alive]:
                if found[cid]:
                    log("gone", found[cid]["labels"]["container"])
                found.pop(cid); checked.pop(cid, None)
            targets = sorted((t for t in found.values() if t), key=lambda t: t["labels"]["container"])
            if targets != last_written:
                with open(TARGETS_FILE + ".tmp", "w") as f:
                    json.dump(targets, f, indent=2)
                os.replace(TARGETS_FILE + ".tmp", TARGETS_FILE)  # atomic: Prometheus never reads half a file
                last_written = targets
                log("wrote", len(targets), "targets")
        except Exception as e:
            log("error:", e)
        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    main()

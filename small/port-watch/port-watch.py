#!/usr/bin/env python3
"""Which TCP ports does this host listen on, and which of them can the internet reach?

Runs in the host's network and PID namespace (docker-compose.yml), so it sees every listener:
host services (sshd, postgres) and Docker-published ports alike. Every SCAN_INTERVAL seconds:
  1. reads /proc/net/tcp and tcp6 for sockets in LISTEN state, and finds the owning process
     through /proc/<pid>/fd (best effort: needs pid: host and SYS_PTRACE);
  2. for each one listening on all interfaces (0.0.0.0 / ::), connects to PUBLIC_IP:<port>.
     A successful connect means no firewall closes it. Docker publishes ports past ufw/iptables
     INPUT rules, so this is the only reliable check;
  3. serves the result as Prometheus metrics on LISTEN (alert PortExposed in alerts.yml).

PUBLIC_IP: empty = detected automatically (AWS metadata, then ifconfig.me / api.ipify.org), re-checked
every hour; "off" = list ports only, no exposure check.
Ports in ALLOWED_PUBLIC_PORTS (e.g. 22,80,443) are expected to be open and get allowed="true".
Limits: TCP only; checking your own public IP from inside can fail on clouds without hairpin
NAT (then port_watch_public_check_ok is 0 and alert PortWatchBlind fires); a cloud firewall in
front of the server is not visible from here, so a port it closes may still be reported.
"""
import os
import socket
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PUBLIC_IP_SETTING = os.environ.get("PUBLIC_IP", "").strip()
PUBLIC_IP = ""
DETECT_EVERY = 3600
ALLOWED = {int(p) for p in os.environ.get("ALLOWED_PUBLIC_PORTS", "").replace(" ", "").split(",") if p}
INTERVAL = int(os.environ.get("SCAN_INTERVAL", "60"))
LISTEN = os.environ.get("LISTEN", "172.17.0.1:39190")
TIMEOUT = 2.0

metrics = "# no scan yet\n"


def listeners():
    """{(address, port): inode} for every TCP socket in LISTEN state (st == 0A)."""
    out = {}
    for path, v6 in (("/proc/net/tcp", False), ("/proc/net/tcp6", True)):
        try:
            lines = open(path).read().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            f = line.split()
            if f[3] != "0A":
                continue
            hexaddr, hexport = f[1].split(":")
            raw = bytes.fromhex(hexaddr)
            if v6:  # /proc stores IPv6 as four little-endian 32-bit words
                raw = b"".join(raw[i:i + 4][::-1] for i in range(0, 16, 4))
                addr = socket.inet_ntop(socket.AF_INET6, raw)
            else:
                addr = socket.inet_ntop(socket.AF_INET, raw[::-1])
            out[(addr, int(hexport, 16))] = f[9]
    return out


def processes():
    """{socket inode: process name} from /proc/<pid>/fd links (socket:[inode])."""
    out = {}
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            name = open(f"/proc/{pid}/comm").read().strip()
            for fd in os.listdir(f"/proc/{pid}/fd"):
                link = os.readlink(f"/proc/{pid}/fd/{fd}")
                if link.startswith("socket:["):
                    out.setdefault(link[8:-1], name)
        except OSError:
            continue
    return out


def detect_public_ip():
    """The address the internet sees. AWS metadata first (no third party involved), then public echo services."""
    def get(url, headers=None, method="GET"):
        req = urllib.request.Request(url, headers=headers or {}, method=method)
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.read().decode().strip()
    try:  # AWS IMDSv2: token, then the instance's public IPv4 (absent for instances without one)
        token = get("http://169.254.169.254/latest/api/token", {"X-aws-ec2-metadata-token-ttl-seconds": "60"}, "PUT")
        ip = get("http://169.254.169.254/latest/meta-data/public-ipv4", {"X-aws-ec2-metadata-token": token})
        socket.inet_aton(ip)
        return ip
    except Exception:
        pass
    for url in ("https://ifconfig.me/ip", "https://api.ipify.org"):
        try:
            ip = get(url)
            socket.inet_aton(ip)
            return ip
        except Exception:
            continue
    return ""


def reachable(port):
    try:
        with socket.create_connection((PUBLIC_IP, port), timeout=TIMEOUT):
            return True
    except OSError:
        return False


def esc(v):
    return str(v).replace("\\", "\\\\").replace('"', '\\"')


def scan():
    socks = listeners()
    names = processes()
    rows = ["# HELP port_watch_listening TCP port in LISTEN state on this host.",
            "# TYPE port_watch_listening gauge"]
    public = {}  # port -> process, for ports on all interfaces
    for (addr, port), inode in sorted(socks.items(), key=lambda x: (x[0][1], x[0][0])):
        proc = names.get(inode, "unknown")
        rows.append(f'port_watch_listening{{address="{esc(addr)}",port="{port}",process="{esc(proc)}"}} 1')
        if addr in ("0.0.0.0", "::"):
            public.setdefault(port, proc)

    if PUBLIC_IP:
        rows += ["# HELP port_watch_reachable 1 = PUBLIC_IP:port accepted a TCP connection (open to the internet).",
                 "# TYPE port_watch_reachable gauge"]
        hits = 0
        for port, proc in sorted(public.items()):
            ok = reachable(port)
            hits += ok
            rows.append(f'port_watch_reachable{{port="{port}",process="{esc(proc)}",'
                        f'allowed="{str(port in ALLOWED).lower()}",public_ip="{esc(PUBLIC_IP)}"}} {int(ok)}')
        # No public port reachable at all while some listen: most likely the host cannot reach its own
        # public IP (no hairpin NAT), so a 0 above means "unknown", not "closed".
        rows += ["# HELP port_watch_public_check_ok 0 = no listening port answered on PUBLIC_IP: the check is blind.",
                 "# TYPE port_watch_public_check_ok gauge",
                 f"port_watch_public_check_ok {int(hits > 0 or not public)}"]
    rows += ["# TYPE port_watch_last_scan_timestamp_seconds gauge", f"port_watch_last_scan_timestamp_seconds {time.time():.0f}"]
    return "\n".join(rows) + "\n"


def loop():
    global metrics, PUBLIC_IP
    detected_at = 0
    while True:
        if not PUBLIC_IP_SETTING and time.time() - detected_at > DETECT_EVERY:
            ip = detect_public_ip()
            if ip != PUBLIC_IP:
                print(f"public IP detected: {ip or 'unknown'}", flush=True)
            PUBLIC_IP, detected_at = ip or PUBLIC_IP, time.time()
        try:
            metrics = scan()
        except Exception as e:  # keep serving the last result; the error shows in docker logs
            print("scan failed:", e, flush=True)
        time.sleep(INTERVAL)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = metrics.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    if PUBLIC_IP_SETTING.lower() == "off":
        print("PUBLIC_IP=off: listing ports only, no exposure check", flush=True)
    elif PUBLIC_IP_SETTING:
        PUBLIC_IP = PUBLIC_IP_SETTING
    threading.Thread(target=loop, daemon=True).start()
    host, port = LISTEN.rsplit(":", 1)
    print(f"serving on {LISTEN}, allowed public ports: {sorted(ALLOWED)}", flush=True)
    ThreadingHTTPServer((host, int(port)), Handler).serve_forever()

#!/usr/bin/env python3
"""Make the bearer token Prometheus needs for MinIO metrics, and test it.

MinIO's /minio/v2/metrics/* endpoints want a JWT signed with a MinIO secret key, the same token
`mc admin prometheus generate` prints. This builds it without mc. The user needs the
admin:Prometheus permission (the root user has it); an app-only user gets 403.

Reads MINIO_ACCESS_KEY, MINIO_SECRET_KEY, MINIO_ENDPOINT, MINIO_PORT, MINIO_USE_SSL from the
environment (make minio-token passes them from .env). Prints the token; put it in .env as
MINIO_PROMETHEUS_TOKEN.
"""
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.request


def b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


def token(access_key, secret_key, years=10):
    head = b64(json.dumps({"alg": "HS512", "typ": "JWT"}).encode())
    body = b64(json.dumps({"exp": int(time.time()) + years * 365 * 86400,
                           "sub": access_key, "iss": "prometheus"}).encode())
    sig = b64(hmac.new(secret_key.encode(), head + b"." + body, hashlib.sha512).digest())
    return (head + b"." + body + b"." + sig).decode()


def main():
    env = os.environ
    missing = [k for k in ("MINIO_ACCESS_KEY", "MINIO_SECRET_KEY", "MINIO_ENDPOINT") if not env.get(k)]
    if missing:
        sys.exit("missing in .env: " + ", ".join(missing))
    tok = token(env["MINIO_ACCESS_KEY"], env["MINIO_SECRET_KEY"])
    scheme = "https" if env.get("MINIO_USE_SSL", "false").lower() == "true" else "http"
    url = f'{scheme}://{env["MINIO_ENDPOINT"]}:{env.get("MINIO_PORT", "9000")}/minio/v2/metrics/cluster'
    try:
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + tok})
        lines = urllib.request.urlopen(req, timeout=10).read().decode().splitlines()
        print(f"OK {url}: {len(lines)} metric lines")
    except Exception as e:  # 403 = user lacks admin:Prometheus; DNS/timeout = endpoint unreachable
        sys.exit(f"ERR {url}: {e}")
    # Prometheus reads the token from this file (job "minio", authorization.credentials_file).
    path = os.path.join(os.path.dirname(__file__), "..", "prometheus", "secrets", "minio-token")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(tok)
    os.chmod(path, 0o644)  # Prometheus runs as nobody inside the container
    print(f"token written to prometheus/secrets/minio-token")


if __name__ == "__main__":
    main()

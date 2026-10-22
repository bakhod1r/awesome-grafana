#!/bin/sh
# Mark a deploy on every Grafana dashboard ("Deploys" annotation, purple line on all graphs).
# Call it from CI after a deploy, or by hand:
#
#   scripts/annotate-deploy.sh my-api "v1.4.2 — new comment API"
#   GRAFANA_URL=https://grafana.example.com GRAFANA_TOKEN=glsa_... scripts/annotate-deploy.sh api "$GIT_SHA"
#
# Auth: GRAFANA_TOKEN (service account token, Editor role) or GRAFANA_ADMIN_USER/PASSWORD (.env).
# Tags: "deploy" (shown by every dashboard) + the service name, so one service's deploys can be filtered.
set -eu
[ $# -ge 1 ] || { echo "usage: $0 <service> [message]" >&2; exit 2; }
service=$1
message=${2:-"deploy $service"}

dir=$(cd "$(dirname "$0")/.." && pwd)
[ -f "$dir/.env" ] && . "$dir/.env"
url=${GRAFANA_URL:-http://localhost:33000}

if [ -n "${GRAFANA_TOKEN:-}" ]; then
  auth="Authorization: Bearer $GRAFANA_TOKEN"
else
  auth="Authorization: Basic $(printf '%s:%s' "${GRAFANA_ADMIN_USER:-admin}" "${GRAFANA_ADMIN_PASSWORD:-admin}" | base64)"
fi

# JSON-escape the free text (quotes and backslashes).
esc() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }

curl -fsS -X POST "$url/api/annotations" -H "$auth" -H "Content-Type: application/json" \
  -d "{\"tags\":[\"deploy\",\"$(esc "$service")\"],\"text\":\"$(esc "$service"): $(esc "$message")\"}"
echo

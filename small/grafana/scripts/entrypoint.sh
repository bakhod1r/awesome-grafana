#!/bin/sh
# Grafana expands ${VAR} in provisioning files, but a numeric value (like a Telegram chat_id)
# loses its quotes and fails validation ("cannot unmarshal number ... of type string").
# So we copy provisioning to a writable dir and substitute __TELEGRAM_CHAT_ID__ ourselves,
# keeping it inside quotes.
set -eu
src=/etc/grafana/provisioning
dst=/tmp/provisioning
mkdir -p "$dst"
cp -R "$src"/. "$dst"/
# Grafana also scans these; create them so it does not log "no such file or directory".
mkdir -p "$dst/plugins" "$dst/notifiers"
chat_id=$(printf '%s' "$TELEGRAM_CHAT_ID" | sed 's/[|&\\]/\\&/g')
topic_id=$(printf '%s' "${TELEGRAM_TOPIC_ID:-}" | sed 's/[|&\\]/\\&/g')
sed -i -e "s|__TELEGRAM_CHAT_ID__|$chat_id|g" -e "s|__TELEGRAM_TOPIC_ID__|$topic_id|g" "$dst"/alerting/*.yml
export GF_PATHS_PROVISIONING="$dst"
exec /run.sh "$@"

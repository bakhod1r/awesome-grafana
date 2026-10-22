#!/bin/sh
# Alertmanager does not expand env vars in its config, so render ${VAR} placeholders before start.
set -eu   # stop on any error or unset variable instead of starting with a broken config

# Defaults for optional values. := assigns only when the variable is unset or empty.
: "${TELEGRAM_TOPIC_ID:=}"
# Warning topic falls back to the critical topic only when warnings go to the same group:
# a topic id from one group means nothing in another.
if [ -z "${TELEGRAM_WARNING_CHAT_ID:-}" ]; then
  : "${TELEGRAM_WARNING_TOPIC_ID:=$TELEGRAM_TOPIC_ID}"
fi
: "${TELEGRAM_WARNING_TOPIC_ID:=}"
: "${TELEGRAM_WARNING_CHAT_ID:=$TELEGRAM_CHAT_ID}"
: "${GRAFANA_URL:=http://localhost:3000}"
export TELEGRAM_TOPIC_ID TELEGRAM_WARNING_TOPIC_ID TELEGRAM_WARNING_CHAT_ID GRAFANA_URL

# render SRC DST: copy SRC to DST, replacing each ${VAR} from the list with its value.
render() {
  out=$(cat "$1")
  for var in TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID TELEGRAM_TOPIC_ID TELEGRAM_WARNING_CHAT_ID TELEGRAM_WARNING_TOPIC_ID GRAFANA_URL; do
    eval "val=\$$var"                                   # value of the variable named in $var
    # Escape characters that are special in the sed replacement (| & \\), e.g. & in URLs.
    val=$(printf '%s' "$val" | sed 's/[|&\\]/\\&/g')
    out=$(printf '%s\n' "$out" | sed "s|\${$var}|$val|g")
  done
  printf '%s\n' "$out" > "$2"
}

# Rendered files go to /tmp because the config directory is mounted read-only.
mkdir -p /tmp/am/templates
render /etc/alertmanager/alertmanager.yml /tmp/am/alertmanager.yml
for f in /etc/alertmanager/templates/*.tmpl; do render "$f" "/tmp/am/templates/$(basename "$f")"; done

# exec replaces this shell with Alertmanager, so it runs as PID 1 and receives stop signals.
exec /bin/alertmanager \
  --config.file=/tmp/am/alertmanager.yml \
  --storage.path=/alertmanager \
  --web.external-url="${ALERTMANAGER_URL:-http://localhost:9093}" \
  "$@"

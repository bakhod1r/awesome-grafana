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
: "${GRAFANA_URL:=http://localhost:33000}"
: "${ALERT_ENV:=}"           # shown first in every message (prod, staging...); empty = not shown
: "${TELEGRAM_MENTIONS:=}"   # tagged on P1/P2, e.g. "@user1 @user2"; empty = nobody
export TELEGRAM_TOPIC_ID TELEGRAM_WARNING_TOPIC_ID TELEGRAM_WARNING_CHAT_ID GRAFANA_URL

# Per-category destinations (receivers <category>-critical / -warning in alertmanager.yml).
# TELEGRAM_TOPIC_<CATEGORY> set (topic ids from the topic links): both severities go to that topic of TELEGRAM_CHAT_ID.
# Not set: critical goes where telegram-critical goes, warning where telegram-warning goes.
vars="TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID TELEGRAM_TOPIC_ID TELEGRAM_WARNING_CHAT_ID TELEGRAM_WARNING_TOPIC_ID GRAFANA_URL ALERT_ENV TELEGRAM_MENTIONS"
for cat in SERVER CONTAINERS SITES DATABASE LOGS SRE DEPLOYS; do
  eval "topic=\${TELEGRAM_TOPIC_$cat:-}"
  if [ -n "$topic" ]; then
    eval "TG_${cat}_CRIT_CHAT=\$TELEGRAM_CHAT_ID TG_${cat}_CRIT_TOPIC=\$topic TG_${cat}_WARN_CHAT=\$TELEGRAM_CHAT_ID TG_${cat}_WARN_TOPIC=\$topic"
  else
    eval "TG_${cat}_CRIT_CHAT=\$TELEGRAM_CHAT_ID TG_${cat}_CRIT_TOPIC=\$TELEGRAM_TOPIC_ID TG_${cat}_WARN_CHAT=\$TELEGRAM_WARNING_CHAT_ID TG_${cat}_WARN_TOPIC=\$TELEGRAM_WARNING_TOPIC_ID"
  fi
  # Who to tag for this category: TELEGRAM_MENTIONS_<CATEGORY>, else TELEGRAM_MENTIONS.
  eval "TELEGRAM_MENTIONS_$cat=\${TELEGRAM_MENTIONS_$cat:-\$TELEGRAM_MENTIONS}"
  vars="$vars TG_${cat}_CRIT_CHAT TG_${cat}_CRIT_TOPIC TG_${cat}_WARN_CHAT TG_${cat}_WARN_TOPIC TELEGRAM_MENTIONS_$cat"
done

# render SRC DST: copy SRC to DST, replacing each ${VAR} from the list with its value.
render() {
  out=$(cat "$1")
  for var in $vars; do
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
  --web.external-url="${ALERTMANAGER_URL:-http://localhost:39093}" \
  "$@"

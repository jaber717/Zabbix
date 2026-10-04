#!/usr/bin/env bash
# build-wan-wall.sh — regenerate grafana/dashboards/noc-wan-overview.json from
# grafana/config/sites.yaml by discovering real itemids live through the
# Grafana → Zabbix datasource resource proxy (as `grafana-ro`, which has
# host.get + item.get permissions). This is how we avoid any new site needing
# to hand-edit a dashboard JSON — change sites.yaml, rerun this script.
#
# Reads bundle creds from $BUNDLE/{grafana.env,claude-access.env}.
# Writes the dashboard JSON to grafana/dashboards/noc-wan-overview.json.
# Does NOT deploy; use grafana/bin/apply-grafana.sh after.
set -euo pipefail

: "${BUNDLE:=$HOME/.config/netops/claude-access}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
CFG="$HERE/config/sites.yaml"
OUT_FILE="$HERE/dashboards/noc-wan-overview.json"
[ -s "$CFG" ] || { echo "missing $CFG"; exit 2; }
[ -s "$BUNDLE/grafana.env" ] || { echo "missing $BUNDLE/grafana.env"; exit 2; }

getenv() { grep -m1 "^${1}=" "$2" 2>/dev/null | sed -E "s/^${1}=//; s/\r$//; s/^\"(.*)\"$/\1/"; }
GRAFANA_URL=$(getenv GRAFANA_URL "$BUNDLE/grafana.env")
GAUTH=$(printf '%s:%s' "$(getenv GRAFANA_ADMIN_USER "$BUNDLE/grafana.env")" \
                       "$(printf '%s' "$(getenv GRAFANA_ADMIN_PASSWORD_B64 "$BUNDLE/grafana.env")" | base64 -d)" | base64 -w0)
DS_UID=$(awk '/^grafana:/{g=1;next} g && /datasource_uid:/{print $2; exit}' "$CFG")
FOLDER_UID=$(awk '/^grafana:/{g=1;next} g && /folder_uid:/{print $2; exit}' "$CFG")
: "${DS_UID:?datasource_uid missing in sites.yaml}"
Z_API() { curl -skS -H "Authorization: Basic $GAUTH" -X POST -H 'Content-Type: application/json' \
          "$GRAFANA_URL/api/datasources/uid/${DS_UID}/resources/zabbix-api" --data "$1"; }

# Parse the slots: lines under `noc_wan_overview.slots:` of the form
#   - { host: X, interface_pattern: Y, label: Z }
mapfile -t SLOTS < <(awk '
  /^noc_wan_overview:/ {in_sec=1; next}
  in_sec && /^[^ ]/ && !/^noc_wan_overview:/ {in_sec=0}
  in_sec && /^\s*- *\{/ {print}
' "$CFG")
[ "${#SLOTS[@]}" -gt 0 ] || { echo "no slots in sites.yaml"; exit 3; }

echo "resolving itemids for ${#SLOTS[@]} slots..."
PANELS_JSON=""
PANEL_ID=0
Y=0
COLS=$(awk '/^noc_wan_overview:/{s=1;next} s && /^  layout:/{l=1;next} l && /columns:/{print $2; exit}' "$CFG")
: "${COLS:=3}"
W=$((24 / COLS))

for i in "${!SLOTS[@]}"; do
  line="${SLOTS[$i]}"
  host=$(printf '%s' "$line" | sed -nE 's/.*host:\s*([A-Z0-9-]+).*/\1/p')
  iface=$(printf '%s' "$line" | sed -nE 's/.*interface_pattern:\s*'"'"'?([^,'"'"'}]+).*/\1/p' | sed -E 's/\s+$//')
  label=$(printf '%s' "$line" | sed -nE "s/.*label:\s*'?([^'}]+).*/\1/p" | sed -E 's/\s+$//')
  [ -n "$host" ] && [ -n "$iface" ] || { echo "FAIL: unparseable slot: $line"; exit 4; }

  # 1. Resolve hostid
  HID=$(Z_API "{\"method\":\"host.get\",\"params\":{\"output\":[\"hostid\"],\"filter\":{\"host\":\"$host\"}}}" \
        | grep -oE '"hostid":"[0-9]+"' | head -1 | grep -oE '[0-9]+')
  [ -n "$HID" ] || { echo "FAIL: host $host not found"; exit 5; }

  # 2. Resolve IN/OUT itemids by name match on the interface + direction keyword.
  #    One Z_API call, then grep the compact JSON: each object is
  #    {"itemid":"NNN","name":"Interface Gi0/0(...): Bits (received|sent)"}
  resp=$(Z_API "{\"method\":\"item.get\",\"params\":{\"output\":[\"itemid\",\"name\"],\"hostids\":[\"$HID\"],\"search\":{\"name\":\"Interface ${iface}\"}}}")
  IN=$(printf '%s' "$resp" | grep -oE '\{"itemid":"[0-9]+","name":"[^"]*Bits received"\}' \
       | head -1 | grep -oE '"itemid":"[0-9]+"' | grep -oE '[0-9]+')
  OUT=$(printf '%s' "$resp" | grep -oE '\{"itemid":"[0-9]+","name":"[^"]*Bits sent"\}' \
        | head -1 | grep -oE '"itemid":"[0-9]+"' | grep -oE '[0-9]+')
  [ -n "$IN" ] && [ -n "$OUT" ] || { echo "FAIL: $host $iface IN/OUT itemids missing (in=$IN out=$OUT)"; exit 6; }

  echo "  slot $((i+1)): $host $iface  IN=$IN OUT=$OUT"

  PANEL_ID=$((PANEL_ID+1))
  X=$(( (i % COLS) * W ))
  if [ $((i % COLS)) -eq 0 ] && [ $i -gt 0 ]; then Y=$((Y+10)); fi

  PANEL=$(cat <<JSON
{"id":${PANEL_ID},"type":"timeseries","title":"${label}","datasource":{"type":"alexanderzobnin-zabbix-datasource","uid":"${DS_UID}"},
"gridPos":{"h":10,"w":${W},"x":${X},"y":${Y}},
"fieldConfig":{"defaults":{"unit":"bps","min":0,"custom":{"drawStyle":"line","lineWidth":1,"fillOpacity":10,"spanNulls":false,"showPoints":"never"},"color":{"mode":"palette-classic"}},
"overrides":[
  {"matcher":{"id":"byRefId","options":"A"},"properties":[{"id":"displayName","value":"IN"},{"id":"color","value":{"mode":"fixed","fixedColor":"#2EA043"}}]},
  {"matcher":{"id":"byRefId","options":"B"},"properties":[{"id":"displayName","value":"OUT"},{"id":"color","value":{"mode":"fixed","fixedColor":"#1F6FEB"}}]}
]},
"options":{"tooltip":{"mode":"multi"},"legend":{"displayMode":"list","placement":"bottom","calcs":["last","max"]}},
"targets":[
  {"refId":"A","queryType":"3","itemids":"${IN}","resultFormat":"time_series"},
  {"refId":"B","queryType":"3","itemids":"${OUT}","resultFormat":"time_series"}
]}
JSON
)
  PANELS_JSON="${PANELS_JSON}${PANELS_JSON:+,}${PANEL}"
done

cat > "$OUT_FILE" <<JSON
{
  "title": "NOC — WAN Overview",
  "uid": "noc-wan-overview",
  "schemaVersion": 39, "version": 1, "editable": false, "graphTooltip": 1,
  "refresh": "30s", "time": {"from": "now-1h", "to": "now"},
  "timepicker": {"refresh_intervals": ["30s","1m","5m"], "time_options": ["1h","6h","24h","7d"]},
  "fiscalYearStartMonth": 0, "liveNow": false, "weekStart": "", "style": "dark",
  "timezone": "browser", "tags": ["netops","wan","wallboard"],
  "templating": {"list": []}, "annotations": {"list": []},
  "panels": [ ${PANELS_JSON} ],
  "description": "Generated by grafana/discovery/build-wan-wall.sh from grafana/config/sites.yaml at $(date -u +%Y-%m-%dT%H:%M:%SZ). Datasource UID ${DS_UID}, folder ${FOLDER_UID}. Fixed slot order; itemids resolved live via Grafana→Zabbix resource proxy."
}
JSON

echo "wrote $OUT_FILE"
unset GAUTH

#!/usr/bin/env bash
# build-device-health.sh — regenerate grafana/dashboards/noc-device-health.json
# from grafana/config/sites.yaml. Discovers one itemid per (host, metric) via
# the Grafana→Zabbix datasource resource proxy, then composes:
#   row 1: memory timeseries (one series per host)
#   row 2: ICMP stat tiles (one per host)
#   row 3: SNMP agent availability stat tiles (one per host)
# CPU is intentionally skipped — the stock IOS dependent `#1: CPU utilization`
# items don't have history on this lab yet (see docs/PORTABILITY.md).
set -euo pipefail

: "${BUNDLE:=$HOME/.config/netops/claude-access}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
CFG="$HERE/config/sites.yaml"
OUT_FILE="$HERE/dashboards/noc-device-health.json"
[ -s "$CFG" ] || { echo "missing $CFG"; exit 2; }

getenv() { grep -m1 "^${1}=" "$2" 2>/dev/null | sed -E "s/^${1}=//; s/\r$//; s/^\"(.*)\"$/\1/"; }
GRAFANA_URL=$(getenv GRAFANA_URL "$BUNDLE/grafana.env")
GAUTH=$(printf '%s:%s' "$(getenv GRAFANA_ADMIN_USER "$BUNDLE/grafana.env")" \
                       "$(printf '%s' "$(getenv GRAFANA_ADMIN_PASSWORD_B64 "$BUNDLE/grafana.env")" | base64 -d)" | base64 -w0)
DS_UID=$(awk '/^grafana:/{g=1;next} g && /datasource_uid:/{print $2; exit}' "$CFG")
Z_API() { curl -skS -H "Authorization: Basic $GAUTH" -X POST -H 'Content-Type: application/json' \
          "$GRAFANA_URL/api/datasources/uid/${DS_UID}/resources/zabbix-api" --data "$1"; }

# Pull the host list under noc_device_health.hosts.
mapfile -t HOSTS < <(awk '
  /^noc_device_health:/ {in_dh=1; next}
  in_dh && /^[^ ]/ {in_dh=0}
  in_dh && /^  hosts:/ {in_hosts=1; next}
  in_dh && in_hosts && /^    - / {gsub(/^    - */,""); print}
' "$CFG")
[ ${#HOSTS[@]} -gt 0 ] || { echo "no hosts under noc_device_health in sites.yaml"; exit 3; }
echo "resolving metrics for ${#HOSTS[@]} hosts: ${HOSTS[*]}"

# Helper: resolve itemid for a given (hostid, item_name_exact).
resolve_itemid() {
  local hid="$1" name="$2"
  Z_API "{\"method\":\"item.get\",\"params\":{\"output\":[\"itemid\"],\"hostids\":[\"$hid\"],\"filter\":{\"name\":\"$name\"}}}" \
    | grep -oE '"itemid":"[0-9]+"' | head -1 | grep -oE '[0-9]+'
}
# Helper: hostid lookup
resolve_hostid() {
  local h="$1"
  Z_API "{\"method\":\"host.get\",\"params\":{\"output\":[\"hostid\"],\"filter\":{\"host\":\"$h\"}}}" \
    | grep -oE '"hostid":"[0-9]+"' | head -1 | grep -oE '[0-9]+'
}

MEM_TARGETS=""
ICMP_PANELS=""
SNMP_PANELS=""
REFS=(A B C D E F G H)   # supports up to 8 hosts
MEM_OVERRIDES=""
Y_ICMP=10
Y_SNMP=14

for i in "${!HOSTS[@]}"; do
  host="${HOSTS[$i]}"
  hid=$(resolve_hostid "$host") || true
  [ -n "$hid" ] || { echo "FAIL: host $host not in Zabbix"; exit 4; }
  memid=$(resolve_itemid "$hid" "Processor: Memory utilization")
  icmpid=$(resolve_itemid "$hid" "ICMP ping")
  snmpid=$(resolve_itemid "$hid" "SNMP agent availability")
  [ -n "$memid" ] && [ -n "$icmpid" ] && [ -n "$snmpid" ] \
    || { echo "FAIL: $host  memid=$memid  icmpid=$icmpid  snmpid=$snmpid"; exit 5; }
  echo "  $host: hostid=$hid memory=$memid icmp=$icmpid snmp=$snmpid"
  refid="${REFS[$i]}"
  MEM_TARGETS="${MEM_TARGETS}${MEM_TARGETS:+,}{\"refId\":\"${refid}\",\"queryType\":\"3\",\"itemids\":\"${memid}\",\"resultFormat\":\"time_series\"}"
  MEM_OVERRIDES="${MEM_OVERRIDES}${MEM_OVERRIDES:+,}{\"matcher\":{\"id\":\"byRefId\",\"options\":\"${refid}\"},\"properties\":[{\"id\":\"displayName\",\"value\":\"${host}\"}]}"
  X=$(( i * 3 ))
  ICMP_PANELS="${ICMP_PANELS}${ICMP_PANELS:+,}$(cat <<JSON
{"id":$((100+i)),"type":"stat","title":"${host} — ICMP","datasource":{"type":"alexanderzobnin-zabbix-datasource","uid":"${DS_UID}"},
"gridPos":{"h":4,"w":3,"x":${X},"y":${Y_ICMP}},
"fieldConfig":{"defaults":{"mappings":[{"type":"value","options":{"0":{"text":"DOWN","color":"red"},"1":{"text":"UP","color":"green"}}}],"color":{"mode":"thresholds"},"thresholds":{"mode":"absolute","steps":[{"color":"red","value":null},{"color":"green","value":1}]}},"overrides":[]},
"options":{"reduceOptions":{"values":false,"calcs":["lastNotNull"]},"textMode":"value","colorMode":"background","graphMode":"none"},
"targets":[{"refId":"A","queryType":"3","itemids":"${icmpid}","resultFormat":"time_series"}]}
JSON
)"
  SNMP_PANELS="${SNMP_PANELS}${SNMP_PANELS:+,}$(cat <<JSON
{"id":$((200+i)),"type":"stat","title":"SNMP — ${host}","datasource":{"type":"alexanderzobnin-zabbix-datasource","uid":"${DS_UID}"},
"gridPos":{"h":4,"w":3,"x":${X},"y":${Y_SNMP}},
"fieldConfig":{"defaults":{"mappings":[{"type":"value","options":{"0":{"text":"UNKNOWN","color":"orange"},"1":{"text":"AVAILABLE","color":"green"},"2":{"text":"UNAVAILABLE","color":"red"}}}],"color":{"mode":"thresholds"},"thresholds":{"mode":"absolute","steps":[{"color":"orange","value":null},{"color":"green","value":1},{"color":"red","value":2}]}},"overrides":[]},
"options":{"reduceOptions":{"values":false,"calcs":["lastNotNull"]},"textMode":"value","colorMode":"background","graphMode":"none"},
"targets":[{"refId":"A","queryType":"3","itemids":"${snmpid}","resultFormat":"time_series"}]}
JSON
)"
done

cat > "$OUT_FILE" <<JSON
{
  "title": "NOC — Device Health",
  "uid": "noc-device-health",
  "schemaVersion": 39, "version": 1, "editable": false, "graphTooltip": 1,
  "refresh": "30s", "time": {"from": "now-1h", "to": "now"},
  "timepicker": {"refresh_intervals": ["30s","1m","5m"], "time_options": ["1h","6h","24h","7d"]},
  "fiscalYearStartMonth": 0, "liveNow": false, "weekStart": "", "style": "dark", "timezone": "browser",
  "tags": ["netops","device-health"],
  "templating": {"list": []}, "annotations": {"list": []},
  "panels": [
    {"id":1,"type":"timeseries","title":"Processor memory utilization — ${#HOSTS[@]} PNET IOSv routers","datasource":{"type":"alexanderzobnin-zabbix-datasource","uid":"${DS_UID}"},
     "gridPos":{"h":10,"w":24,"x":0,"y":0},
     "fieldConfig":{"defaults":{"unit":"percent","min":0,"max":100,"custom":{"drawStyle":"line","lineWidth":1,"fillOpacity":10,"spanNulls":false,"showPoints":"never"},"color":{"mode":"palette-classic"},
     "thresholds":{"mode":"absolute","steps":[{"color":"transparent","value":null},{"color":"orange","value":70},{"color":"red","value":90}]}},
     "overrides":[${MEM_OVERRIDES}]},
     "options":{"tooltip":{"mode":"multi"},"legend":{"displayMode":"table","placement":"right","calcs":["last","mean","max"]}},
     "targets":[${MEM_TARGETS}]},
    ${ICMP_PANELS},
    ${SNMP_PANELS}
  ],
  "description": "Generated by grafana/discovery/build-device-health.sh from grafana/config/sites.yaml at $(date -u +%Y-%m-%dT%H:%M:%SZ). Datasource UID ${DS_UID}. CPU timeseries intentionally omitted — the stock IOS dependent CPU items don't have history yet. See docs/PORTABILITY.md."
}
JSON
echo "wrote $OUT_FILE"
unset GAUTH

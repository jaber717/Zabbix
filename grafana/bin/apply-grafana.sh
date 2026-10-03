#!/usr/bin/env bash
# apply-grafana.sh — deploy the NetOps datasource + dashboards into a running
# Grafana. Two modes:
#
#   api   — hit grafana-01's HTTP API with admin credentials. Works even when
#           we don't have SSH to the Grafana LXC. Does NOT use provisioning
#           files; it uses /api/datasources and /api/dashboards/db directly.
#           Side effect: dashboards show "Provisioned: false" in the UI.
#
#   files — rsync the provisioning/ tree into /etc/grafana/provisioning/ on
#           grafana-01 and reload grafana-server. True dashboard-as-code.
#           Requires SSH to grafana-01 (Codex has to add it to ssh-config).
#
# This script reads grafana access from the Claude access bundle; secrets are
# base64-decoded in memory, never echoed, never written to disk here.
set -euo pipefail

MODE="${1:-api}"
BUNDLE="${BUNDLE:-$HOME/.config/netops/claude-access}"
[ -s "$BUNDLE/grafana.env" ] || { echo "missing $BUNDLE/grafana.env"; exit 2; }

# shellcheck disable=SC1091
. "$BUNDLE/grafana.env"
: "${GRAFANA_URL:?GRAFANA_URL missing in grafana.env}"
: "${GRAFANA_ADMIN_USER:?GRAFANA_ADMIN_USER missing}"
: "${GRAFANA_ADMIN_PASSWORD_B64:?GRAFANA_ADMIN_PASSWORD_B64 missing}"
: "${ZABBIX_GRAFANA_USER:?ZABBIX_GRAFANA_USER missing}"
: "${ZABBIX_GRAFANA_PASSWORD_B64:?ZABBIX_GRAFANA_PASSWORD_B64 missing}"

GRAFANA_ADMIN_PASSWORD=$(printf '%s' "$GRAFANA_ADMIN_PASSWORD_B64" | base64 -d)
ZABBIX_GRAFANA_PASSWORD=$(printf '%s' "$ZABBIX_GRAFANA_PASSWORD_B64" | base64 -d)
unset GRAFANA_ADMIN_PASSWORD_B64 ZABBIX_GRAFANA_PASSWORD_B64
AUTH="${GRAFANA_ADMIN_USER}:${GRAFANA_ADMIN_PASSWORD}"
cleanup() { unset GRAFANA_ADMIN_PASSWORD ZABBIX_GRAFANA_PASSWORD AUTH; }
trap cleanup EXIT

grafana_reachable() {
  curl -skS -m 5 "$GRAFANA_URL/api/health" >/dev/null 2>&1
}
grafana_reachable || { echo "$GRAFANA_URL unreachable"; exit 3; }

api_mode() {
  echo "== probing plugin =="
  if ! curl -skS -u "$AUTH" "$GRAFANA_URL/api/plugins" | grep -q 'alexanderzobnin-zabbix'; then
    echo "FATAL alexanderzobnin-zabbix-app plugin not installed. Install on grafana-01:"
    echo "      grafana-cli plugins install alexanderzobnin-zabbix-app && systemctl restart grafana-server"
    exit 4
  fi

  echo "== create/update datasource =="
  DS_PAYLOAD=$(cat <<JSON
{
  "name": "Zabbix NOC", "uid": "zbx-noc",
  "type": "alexanderzobnin-zabbix-datasource", "access": "proxy",
  "url": "https://192.168.1.91:8443/api_jsonrpc.php",
  "editable": false, "isDefault": true,
  "jsonData": {
    "username": "${ZABBIX_GRAFANA_USER}", "trends": true,
    "trendsFrom": "7d", "trendsRange": "4d", "cacheTTL": "60s",
    "alerting": false, "disableReadOnlyUsersAck": true, "tlsSkipVerify": true
  },
  "secureJsonData": {"password": "${ZABBIX_GRAFANA_PASSWORD}"}
}
JSON
)
  # Upsert via uid.
  code=$(curl -skS -u "$AUTH" -o /tmp/ds.resp -w '%{http_code}' -H 'Content-Type: application/json' \
    -X POST --data "$DS_PAYLOAD" "$GRAFANA_URL/api/datasources")
  if [ "$code" = 409 ]; then
    DS_ID=$(curl -skS -u "$AUTH" "$GRAFANA_URL/api/datasources/uid/zbx-noc" | sed -E 's/.*"id":([0-9]+).*/\1/')
    code=$(curl -skS -u "$AUTH" -o /tmp/ds.resp -w '%{http_code}' -H 'Content-Type: application/json' \
      -X PUT --data "$DS_PAYLOAD" "$GRAFANA_URL/api/datasources/${DS_ID}")
  fi
  [ "$code" = 200 ] || { echo "datasource upsert failed: HTTP $code"; cat /tmp/ds.resp; exit 5; }
  echo "datasource OK"

  echo "== upsert folder =="
  curl -skS -u "$AUTH" -X POST -H 'Content-Type: application/json' \
    -d '{"uid":"netops-noc","title":"NetOps NOC"}' "$GRAFANA_URL/api/folders" >/dev/null || true

  echo "== upsert dashboards =="
  for f in grafana/dashboards/*.json; do
    [ -s "$f" ] || continue
    # Wrap the dashboard body in the dashboards/db envelope.
    jq -n --slurpfile dash "$f" '{dashboard: $dash[0], folderUid: "netops-noc", overwrite: true, message: "apply-grafana.sh"}' \
      > /tmp/dash.body
    code=$(curl -skS -u "$AUTH" -o /tmp/dash.resp -w '%{http_code}' \
      -X POST -H 'Content-Type: application/json' --data @/tmp/dash.body \
      "$GRAFANA_URL/api/dashboards/db")
    [ "$code" = 200 ] || { echo "dashboard $f failed: HTTP $code"; cat /tmp/dash.resp; exit 6; }
    echo "  $f OK"
  done
}

files_mode() {
  echo "== rsync provisioning/ to grafana-01 =="
  rsync -az --delete grafana/provisioning/ grafana-01:/etc/grafana/provisioning/
  rsync -az --delete grafana/dashboards/   grafana-01:/var/lib/grafana/dashboards/netops-noc/
  ssh grafana-01 'systemctl reload grafana-server || systemctl restart grafana-server'
  echo "files_mode done; Grafana will reload provisioning"
}

case "$MODE" in
  api)   api_mode;;
  files) files_mode;;
  *) echo "usage: $0 [api|files]"; exit 2;;
esac

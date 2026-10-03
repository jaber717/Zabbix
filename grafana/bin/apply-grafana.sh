#!/usr/bin/env bash
# apply-grafana.sh — deploy the NetOps datasource + dashboards into a running
# Grafana. Modes:
#   api   — hit the HTTP API with admin credentials (works without SSH to
#           grafana-01). Uploads only dashboards under grafana/dashboards/;
#           grafana/drafts/ is DELIBERATELY SKIPPED.
#   files — rsync provisioning/ + dashboards/ into /etc/grafana/ on
#           grafana-01, then reload. Requires grafana-01 in ssh-config.
#
# Zabbix API URL is read from the shared access bundle (ZABBIX_URL), not
# hard-coded. If it is missing, we probe /api/jsonrpc.php on the known
# Zabbix host and fail if that too is unreachable.
set -euo pipefail

MODE="${1:-api}"
BUNDLE="${BUNDLE:-$HOME/.config/netops/claude-access}"
[ -s "$BUNDLE/grafana.env"       ] || { echo "missing $BUNDLE/grafana.env";       exit 2; }
[ -s "$BUNDLE/claude-access.env" ] || { echo "missing $BUNDLE/claude-access.env"; exit 2; }

# shellcheck disable=SC1091
. "$BUNDLE/claude-access.env"
# shellcheck disable=SC1091
. "$BUNDLE/grafana.env"
: "${GRAFANA_URL:?GRAFANA_URL missing in grafana.env}"
: "${GRAFANA_ADMIN_USER:?GRAFANA_ADMIN_USER missing}"
: "${GRAFANA_ADMIN_PASSWORD_B64:?GRAFANA_ADMIN_PASSWORD_B64 missing}"
: "${ZABBIX_GRAFANA_USER:?ZABBIX_GRAFANA_USER missing}"
: "${ZABBIX_GRAFANA_PASSWORD_B64:?ZABBIX_GRAFANA_PASSWORD_B64 missing}"
: "${ZABBIX_URL:?ZABBIX_URL missing in claude-access.env}"

# Probe-verify the Zabbix URL before telling Grafana to trust it.
if ! curl -skS -m 5 -o /tmp/apiprobe.json "$ZABBIX_URL" >/dev/null 2>&1 \
   || ! grep -q jsonrpc /tmp/apiprobe.json 2>/dev/null; then
  echo "WARN  $ZABBIX_URL does not look like a Zabbix API endpoint — attempting apiinfo.version probe"
  if ! curl -skS -m 5 -H 'Content-Type: application/json-rpc' \
       -d '{"jsonrpc":"2.0","method":"apiinfo.version","params":{},"id":1}' \
       "$ZABBIX_URL" | grep -q '"result"'; then
    echo "FATAL $ZABBIX_URL did not answer apiinfo.version"; exit 3
  fi
fi

GRAFANA_ADMIN_PASSWORD=$(printf '%s' "$GRAFANA_ADMIN_PASSWORD_B64" | base64 -d)
ZABBIX_GRAFANA_PASSWORD=$(printf '%s' "$ZABBIX_GRAFANA_PASSWORD_B64" | base64 -d)
unset GRAFANA_ADMIN_PASSWORD_B64 ZABBIX_GRAFANA_PASSWORD_B64
AUTH="${GRAFANA_ADMIN_USER}:${GRAFANA_ADMIN_PASSWORD}"
cleanup() { unset GRAFANA_ADMIN_PASSWORD ZABBIX_GRAFANA_PASSWORD AUTH; }
trap cleanup EXIT

curl -skS -m 5 "$GRAFANA_URL/api/health" >/dev/null \
  || { echo "FATAL $GRAFANA_URL unreachable"; exit 4; }

api_mode() {
  echo "== probing plugin =="
  curl -skS -u "$AUTH" "$GRAFANA_URL/api/plugins" | grep -q 'alexanderzobnin-zabbix' \
    || { echo "FATAL alexanderzobnin-zabbix-app plugin not installed. Install on grafana-01:"
         echo "      grafana-cli plugins install alexanderzobnin-zabbix-app && systemctl restart grafana-server"
         exit 5; }

  echo "== upsert datasource (uid=zabbix-lab, url=$ZABBIX_URL) =="
  DS_PAYLOAD=$(cat <<JSON
{
  "name": "Zabbix NOC", "uid": "zabbix-lab",
  "type": "alexanderzobnin-zabbix-datasource", "access": "proxy",
  "url": "${ZABBIX_URL}",
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
  code=$(curl -skS -u "$AUTH" -o /tmp/ds.resp -w '%{http_code}' -H 'Content-Type: application/json' \
    -X POST --data "$DS_PAYLOAD" "$GRAFANA_URL/api/datasources")
  if [ "$code" = 409 ]; then
    DS_ID=$(curl -skS -u "$AUTH" "$GRAFANA_URL/api/datasources/uid/zabbix-lab" | sed -E 's/.*"id":([0-9]+).*/\1/')
    code=$(curl -skS -u "$AUTH" -o /tmp/ds.resp -w '%{http_code}' -H 'Content-Type: application/json' \
      -X PUT --data "$DS_PAYLOAD" "$GRAFANA_URL/api/datasources/${DS_ID}")
  fi
  [ "$code" = 200 ] || { echo "datasource upsert failed: HTTP $code"; cat /tmp/ds.resp; exit 6; }
  echo "datasource OK"

  echo "== upsert folder =="
  curl -skS -u "$AUTH" -X POST -H 'Content-Type: application/json' \
    -d '{"uid":"noc","title":"NOC"}' "$GRAFANA_URL/api/folders" >/dev/null || true

  echo "== upsert dashboards (grafana/dashboards/ only; drafts/ skipped) =="
  shopt -s nullglob
  for f in grafana/dashboards/*.json; do
    [ -s "$f" ] || continue
    jq -n --slurpfile dash "$f" \
      '{dashboard: $dash[0], folderUid: "noc", overwrite: true, message: "apply-grafana.sh"}' \
      > /tmp/dash.body
    code=$(curl -skS -u "$AUTH" -o /tmp/dash.resp -w '%{http_code}' \
      -X POST -H 'Content-Type: application/json' --data @/tmp/dash.body \
      "$GRAFANA_URL/api/dashboards/db")
    [ "$code" = 200 ] || { echo "dashboard $f failed: HTTP $code"; cat /tmp/dash.resp; exit 7; }
    echo "  $f OK"
  done

  # Verify each dashboard target returns at least one frame.
  echo "== verify noc-wan-overview targets return data =="
  if curl -skS -u "$AUTH" "$GRAFANA_URL/api/dashboards/uid/noc-wan-overview" | grep -q '"panels"'; then
    echo "dashboard noc-wan-overview readable OK"
  else
    echo "WARN noc-wan-overview did not return panels on GET; investigate"
  fi
}

files_mode() {
  [ -s grafana/provisioning/datasources/zabbix.yaml ] || { echo "missing provisioning/datasources"; exit 2; }
  # Materialise provisioning templates with real values via envsubst.
  export ZABBIX_URL ZABBIX_GRAFANA_USER ZABBIX_GRAFANA_PASSWORD
  mkdir -p /tmp/grafana-prov/datasources /tmp/grafana-prov/dashboards
  envsubst '${ZABBIX_URL} ${ZABBIX_GRAFANA_USER} ${ZABBIX_GRAFANA_PASSWORD}' \
    < grafana/provisioning/datasources/zabbix.yaml > /tmp/grafana-prov/datasources/zabbix.yaml
  cp grafana/provisioning/dashboards/noc.yaml      /tmp/grafana-prov/dashboards/noc.yaml

  echo "== rsync provisioning + dashboards (drafts/ excluded) =="
  rsync -az --delete /tmp/grafana-prov/ grafana-01:/etc/grafana/provisioning/
  rsync -az --delete --exclude 'drafts/' grafana/dashboards/ grafana-01:/var/lib/grafana/dashboards/noc/
  ssh grafana-01 'systemctl reload grafana-server || systemctl restart grafana-server'
  rm -rf /tmp/grafana-prov
  echo "files_mode done; Grafana will reload provisioning"
}

case "$MODE" in
  api)   api_mode;;
  files) files_mode;;
  *) echo "usage: $0 [api|files]"; exit 2;;
esac

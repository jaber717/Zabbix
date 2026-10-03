#!/usr/bin/env bash
# clickhouse-apply.sh — idempotent installer for the Zabbix compat view +
# the read-only user used by the Flow API gateway.
#
# Preconditions:
#   - Akvorado's outlet has already created `akvorado.flows`.
#   - /etc/flow-api/ch-pass exists (mode 0640 root:nginx; see bin/stack-up.sh).
#   - The ClickHouse container is reachable as `akvorado-clickhouse`.
#
# Reads the canonical appliance SQL from /opt/akvorado/sql/views.sql. The
# Zabbix module's copy at frontend/modules/FlowSearch/sql/views.sql is the
# UI-side reference and must stay bit-identical; CI should fail on drift.
set -euo pipefail

CH_CONTAINER="${CH_CONTAINER:-akvorado-clickhouse}"
PASS_FILE="${PASS_FILE:-/etc/flow-api/ch-pass}"
SQL_SRC="${SQL_SRC:-/opt/akvorado/sql/views.sql}"

[ -s "$PASS_FILE" ] || { echo "missing $PASS_FILE (0640 root:nginx holds flow_api_ro password)"; exit 2; }
[ -s "$SQL_SRC" ]   || { echo "missing $SQL_SRC";   exit 2; }
PASS=$(cat "$PASS_FILE")

exec_sql() { docker exec -i "$CH_CONTAINER" clickhouse-client --multiquery; }

echo "== check akvorado.flows exists =="
echo "SELECT 1 FROM system.tables WHERE database='akvorado' AND name='flows' LIMIT 1" | exec_sql | grep -q '^1$' || {
  echo "akvorado.flows not found; outlet hasn't initialised schema. Start the stack and wait for first flows." >&2
  exit 3
}

echo "== apply $SQL_SRC =="
sed "s|\${FLOW_API_RO_PASSWORD}|${PASS}|" "$SQL_SRC" | exec_sql
echo "== probe =="
echo "SELECT name FROM system.databases WHERE name='netops' FORMAT TSV; SELECT 'netops.flow_v1 ok' FROM netops.flow_v1 LIMIT 1" | exec_sql
echo "== verify flow_api_ro can SELECT =="
docker exec -i "$CH_CONTAINER" clickhouse-client -u flow_api_ro --password "$PASS" \
    --query "SELECT 'ok' FROM netops.flow_v1 LIMIT 0"
echo "clickhouse-apply.sh DONE"

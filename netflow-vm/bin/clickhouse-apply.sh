#!/usr/bin/env bash
# clickhouse-apply.sh — idempotent installer for the Zabbix compat view +
# the read-only user used by the Flow API gateway.
#
# Preconditions:
#   - The Akvorado stack is up and the outlet has created `akvorado.flows_*`.
#   - /etc/flow-api/ch-pass exists (owner-only, 0600) with the flow_api_ro
#     password. flow-api-install.sh creates this.
#   - The ClickHouse container is reachable at akvorado-clickhouse:9000 inside
#     the compose network.
#
# What it does:
#   1. Verifies the Akvorado flows table exists; aborts clearly otherwise.
#   2. Executes frontend/modules/FlowSearch/sql/views.sql with
#      ${FLOW_API_RO_PASSWORD} substituted from /etc/flow-api/ch-pass.
#   3. Confirms SELECT works as flow_api_ro on netops.flow_v1.
#
# Safe to rerun. Uses CREATE OR REPLACE / CREATE USER IF NOT EXISTS / GRANT.
set -euo pipefail

CH_CONTAINER="${CH_CONTAINER:-akvorado-clickhouse}"
PASS_FILE="${PASS_FILE:-/etc/flow-api/ch-pass}"
SQL_SRC="${SQL_SRC:-/opt/akvorado/sql/views.sql}"

[ -s "$PASS_FILE" ] || { echo "missing $PASS_FILE (owner-only 0600, holds flow_api_ro password)"; exit 2; }
[ -s "$SQL_SRC" ]   || { echo "missing $SQL_SRC";   exit 2; }
PASS=$(cat "$PASS_FILE")

exec_sql() {
  # Pipe multi-statement SQL into the container's clickhouse-client.
  docker exec -i "$CH_CONTAINER" clickhouse-client --multiquery
}

echo "== check akvorado.flows exists =="
echo "SELECT 1 FROM system.tables WHERE database='akvorado' AND name='flows' LIMIT 1" | exec_sql | grep -q '^1$' || {
  echo "akvorado.flows not found; outlet hasn't initialised schema. Start the stack and wait for first flows." >&2
  exit 3
}

echo "== apply views.sql =="
sed "s|\${FLOW_API_RO_PASSWORD}|${PASS}|" "$SQL_SRC" | exec_sql
echo "== probe =="
echo "SELECT name FROM system.databases WHERE name='netops' FORMAT TSV; SELECT 'netops.flow_v1 ok' FROM netops.flow_v1 LIMIT 1" | exec_sql
echo "== verify flow_api_ro can SELECT =="
docker exec -i "$CH_CONTAINER" clickhouse-client -u flow_api_ro --password "$PASS" \
    --query "SELECT 'ok' FROM netops.flow_v1 LIMIT 0"
echo "clickhouse-apply.sh DONE"

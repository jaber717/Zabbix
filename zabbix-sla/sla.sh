#!/usr/bin/env bash
# Zabbix service / SLA platform - the only command an operator runs.
#
#   vi inventory/lab.yaml
#   ./sla.sh --env lab check        validate the inventory (offline)
#   ./sla.sh --env lab plan         ADD / CHANGE / orphan list, nothing is changed
#   ./sla.sh --env lab apply        backup, write, readback-verify
#   ./sla.sh --env lab verify       semantic drift check (exit 2 = drift)
#   ./sla.sh --env lab rollback --backup state/backups/<file>.json
#
# Production writes additionally need --confirm production.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
if [ -f "$HERE/.env" ]; then
  set -a; . "$HERE/.env"; set +a
fi
PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "ERROR: $PY not found (need Python 3.8+ with PyYAML)" >&2; exit 2
fi
if ! "$PY" -c 'import yaml' >/dev/null 2>&1; then
  echo "ERROR: PyYAML missing for $PY (pip install pyyaml  or  apt install python3-yaml)" >&2; exit 2
fi
exec "$PY" -m slaas "$@"

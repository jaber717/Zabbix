#!/usr/bin/env bash
# Discovery-assisted onboarding: read-only discovery -> coverage audit -> review -> both inventories.
#
#   ./onboard.sh --env production                              review (first run asks for URL + token)
#   ./onboard.sh --env production --report                     coverage audit only
#   ./onboard.sh --env production --verify                     deployment gate (fail closed)
#   ./onboard.sh --env production --deploy --confirm production   gate, then apply.sh / apply-health.sh
#
# Everything before --deploy is read-only towards Zabbix and NetBox. See docs/ONBOARDING.md.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "ERROR: $PY not found (RHEL 9: python3 is part of the base OS)" >&2; exit 2
fi
if ! "$PY" -c 'import yaml' >/dev/null 2>&1; then
  echo "ERROR: PyYAML missing for $PY. RHEL 9: sudo dnf install python3-pyyaml (from your configured RHEL repository)" >&2
  exit 2
fi
exec "$PY" -m netalert.onboard_cli "$@"

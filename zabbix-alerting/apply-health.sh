#!/usr/bin/env bash
# Network Health alerting as code (v1.0.3, UNTESTED). Independent of ./apply.sh; reads config/network-health.<env>.yaml.
#
#   vi config/network-health.<env>.yaml
#   ./apply-health.sh --check            validate: PASS/FAIL per device, nothing is changed
#   ./apply-health.sh --dry-run          show ADD / CHANGE / REMOVE, nothing is changed
#   ./apply-health.sh                    apply (asks nothing; prints a banner, takes a backup first)
#
# Another environment:  ./apply-health.sh --env production --check   (production writes need --confirm production)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

if [ -f "$HERE/.env" ]; then
  set -a; . "$HERE/.env"; set +a
fi

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "ERROR: $PY not found (need Python 3.8+ with PyYAML: pip install pyyaml)" >&2; exit 2
fi
if ! "$PY" -c 'import yaml' >/dev/null 2>&1; then
  echo "ERROR: PyYAML missing for $PY (pip install pyyaml  or  apt install python3-yaml)" >&2; exit 2
fi
exec "$PY" -m nethealth.cli "$@"

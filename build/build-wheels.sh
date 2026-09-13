#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd -P)/lib/common.sh"
DEST=${1:-"$PROJECT_ROOT/build/out/wheelhouse"}
mkdir -p "$DEST"
LOCK="$PROJECT_ROOT/integrations/netbox-zabbix-sync/wheels/requirements.lock"

if ! grep -Ev '^[[:space:]]*(#|$)' "$LOCK" | grep -q .; then
  cat > "$DEST/README.txt" <<EOF
The optional NetBox integration uses only the Python standard library.
No third-party wheels are required. The selected ABI is CPython $PYTHON_ABI.
EOF
  echo "PYTHON_ABI=$PYTHON_ABI"
  echo "DEPENDENCY_COUNT=0"
  echo "RESULT=PASS_EMPTY_REQUIREMENTS"
  exit 0
fi

PYTHON="python$PYTHON_ABI"
command -v "$PYTHON" >/dev/null 2>&1 || { echo "missing $PYTHON" >&2; exit 1; }
"$PYTHON" -m pip download --require-hashes --only-binary=:all: --dest "$DEST" -r "$LOCK"
echo "RESULT=PASS"

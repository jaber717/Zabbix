#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd -P)/lib/common.sh"
DEST=${1:-"$PROJECT_ROOT/build/out/wheelhouse"}
mkdir -p "$DEST"
LOCK="$PROJECT_ROOT/integration/wheels/requirements.lock"

if ! grep -Ev '^[[:space:]]*(#|$)' "$LOCK" | grep -q .; then
  cat > "$DEST/README.txt" <<EOF
No third-party wheels are included in M1. The selected ABI is CPython $PYTHON_ABI.
M4 must define and hash-lock real integration requirements before wheel download.
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

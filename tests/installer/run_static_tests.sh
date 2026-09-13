#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)
cd -- "$ROOT"
PYTHON_BIN=${PYTHON_BIN:-python3}

"$PYTHON_BIN" tests/installer/validate_installer.py
"$PYTHON_BIN" -m unittest -v tests/installer/test_helpers.py
PYTHONPATH="$ROOT/integrations/netbox-zabbix-sync" \
  "$PYTHON_BIN" -m unittest -v integrations/netbox-zabbix-sync/tests/test_sync.py

while IFS= read -r script; do
  bash -n "$script"
done < <(find . -path ./.git -prune -o -type f \( -name '*.sh' -o ! -name '*.*' \) -print | LC_ALL=C sort)
printf 'BASH_SYNTAX=PASS\n'

if [[ -f installer/MANIFEST.sha256 ]]; then
  (
    cd installer
    sha256sum --quiet -c MANIFEST.sha256
  )
  printf 'INSTALLER_MANIFEST=PASS\n'
else
  printf 'INSTALLER_MANIFEST=NOT-EXECUTED reason=manifest-not-generated\n'
fi

printf 'RESULT=PASS\n'

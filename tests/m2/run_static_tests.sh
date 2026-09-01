#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)
cd -- "$ROOT"
PYTHON_BIN=${PYTHON_BIN:-python3}

"$PYTHON_BIN" tests/m2/validate_installer.py
"$PYTHON_BIN" -m unittest -v tests/m2/test_helpers.py

while IFS= read -r script; do
  bash -n "$script"
done < <(find installer tests/m2 -type f \( -name '*.sh' -o ! -name '*.*' \) -print | LC_ALL=C sort)
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

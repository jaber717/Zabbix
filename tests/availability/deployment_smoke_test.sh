#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)
PHP_BIN=${PHP_BIN:-php}
TEMP_ROOT=$(mktemp -d)
cleanup() {
  rm -rf -- "$TEMP_ROOT"
}
trap cleanup EXIT

mkdir -p "$TEMP_ROOT/frontend/include" "$TEMP_ROOT/frontend/modules"
printf '%s\n' \
  'ID=rhel' \
  'VERSION_ID="9.6"' \
  'PRETTY_NAME="Red Hat Enterprise Linux 9.6 (isolated test)"' \
  > "$TEMP_ROOT/os-release"
printf '%s\n' "<?php define('ZABBIX_VERSION', '7.0.30');" \
  > "$TEMP_ROOT/frontend/include/defines.inc.php"

run_in_fixture() {
  ZABBIX_FRONTEND_ROOT="$TEMP_ROOT/frontend" \
  NETWORK_AVAILABILITY_OS_RELEASE="$TEMP_ROOT/os-release" \
  PHP_BIN="$PHP_BIN" \
  "$@"
}

PREFLIGHT_OUTPUT=$(run_in_fixture "$ROOT/scripts/install-network-availability.sh" --preflight)
grep -q '^PREFLIGHT=PASS$' <<< "$PREFLIGHT_OUTPUT"

cp -a "$ROOT/frontend/modules/NetworkAvailability" \
  "$TEMP_ROOT/frontend/modules/NetworkAvailability"
VERIFY_OUTPUT=$(run_in_fixture "$ROOT/scripts/verify-network-availability.sh")
grep -q '^MODULE_RELEASE=1.0.1$' <<< "$VERIFY_OUTPUT"
grep -q '^PASS$' <<< "$VERIFY_OUTPUT"

printf '\n// isolated checksum tamper test\n' \
  >> "$TEMP_ROOT/frontend/modules/NetworkAvailability/Widget.php"
if run_in_fixture "$ROOT/scripts/verify-network-availability.sh" >/dev/null 2>&1; then
  printf 'FAIL: verifier accepted a modified release file\n' >&2
  exit 1
fi

printf 'PREFLIGHT=PASS\n'
printf 'READ_ONLY_VERIFY=PASS\n'
printf 'TAMPER_REJECTION=PASS\n'
printf 'RESULT=PASS\n'

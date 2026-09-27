#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)
PHP_BIN=${PHP_BIN:-php}
TEMP_ROOT=$(mktemp -d)
cleanup() {
  rm -rf -- "$TEMP_ROOT"
}
trap cleanup EXIT

mkdir -p "$TEMP_ROOT/frontend/include" "$TEMP_ROOT/frontend/modules" "$TEMP_ROOT/runtime" "$TEMP_ROOT/bin"
printf '%s\n' '#!/usr/bin/env bash' 'exit 1' > "$TEMP_ROOT/bin/selinuxenabled"
chmod 0755 "$TEMP_ROOT/bin/selinuxenabled"
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
  NETWORK_AVAILABILITY_RUNTIME_DIR="$TEMP_ROOT/runtime" \
  NETWORK_AVAILABILITY_RUNTIME_USER="$(id -un)" \
  NETWORK_AVAILABILITY_RUNTIME_GROUP="$(id -gn)" \
  PATH="$TEMP_ROOT/bin:$PATH" \
  PHP_BIN="$PHP_BIN" \
  "$@"
}

PREFLIGHT_OUTPUT=$(run_in_fixture "$ROOT/scripts/install-network-availability.sh" --preflight)
grep -q '^PREFLIGHT=PASS$' <<< "$PREFLIGHT_OUTPUT"

cp -a "$ROOT/frontend/modules/NetworkAvailability" \
  "$TEMP_ROOT/frontend/modules/NetworkAvailability"
cp "$ROOT/frontend/modules/NetworkAvailability/config/node-definitions.json" \
  "$TEMP_ROOT/runtime/node-definitions.json"
chmod 0750 "$TEMP_ROOT/runtime"
chmod 0640 "$TEMP_ROOT/runtime/node-definitions.json"
VERIFY_OUTPUT=$(run_in_fixture "$ROOT/scripts/verify-network-availability.sh")
grep -q '^MODULE_RELEASE=1.2.1$' <<< "$VERIFY_OUTPUT"
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

#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck source=lib/network-availability-common.sh
source "$SCRIPT_DIR/lib/network-availability-common.sh"

usage() {
  cat <<'EOF'
Usage:
  rollback-network-availability.sh --confirm-module-disabled --restore-latest
  rollback-network-availability.sh --confirm-module-disabled --remove-current

Disable Network Availability in the Zabbix UI before running either command.
The current module is moved to a timestamped recovery directory, never deleted.
EOF
}

[[ $# -eq 2 && $1 == '--confirm-module-disabled' ]] || { usage >&2; exit 2; }
ACTION=$2
[[ "$ACTION" == '--restore-latest' || "$ACTION" == '--remove-current' ]] \
  || { usage >&2; exit 2; }

na_require_root
na_validate_environment
TARGET_DIR="$NA_MODULES_DIR/NetworkAvailability"
[[ -d "$TARGET_DIR" ]] || na_fail "installed module not found: $TARGET_DIR"
na_validate_module_structure "$TARGET_DIR"

TIMESTAMP=$(date -u +%Y%m%d-%H%M%S)
if [[ "$ACTION" == '--restore-latest' ]]; then
  BACKUP_NAME=$(find "$NA_MODULES_DIR" -mindepth 1 -maxdepth 1 -type d \
    -name 'NetworkAvailability.backup-*' -printf '%f\n' | LC_ALL=C sort | tail -n 1)
  [[ -n "$BACKUP_NAME" ]] || na_fail 'no NetworkAvailability.backup-* directory is available'
  BACKUP_DIR="$NA_MODULES_DIR/$BACKUP_NAME"
  na_validate_module_structure "$BACKUP_DIR"
  if [[ -r "$BACKUP_DIR/RELEASE.sha256" ]]; then
    na_validate_checksum_manifest "$BACKUP_DIR"
  fi
  na_lint_module_php "$BACKUP_DIR"

  REPLACED_DIR="$NA_MODULES_DIR/NetworkAvailability.rollback-replaced-$TIMESTAMP"
  [[ ! -e "$REPLACED_DIR" ]] || na_fail "recovery path already exists: $REPLACED_DIR"
  mv -- "$TARGET_DIR" "$REPLACED_DIR"
  if ! mv -- "$BACKUP_DIR" "$TARGET_DIR"; then
    mv -- "$REPLACED_DIR" "$TARGET_DIR" || true
    na_fail 'backup restoration failed; current module restoration was attempted'
  fi
  na_info "RESTORED_FROM=$BACKUP_NAME"
  na_info "RESTORED_TO=$TARGET_DIR"
  na_info "REPLACED_MODULE_PRESERVED=$REPLACED_DIR"
else
  REMOVED_DIR="$NA_MODULES_DIR/NetworkAvailability.removed-$TIMESTAMP"
  [[ ! -e "$REMOVED_DIR" ]] || na_fail "recovery path already exists: $REMOVED_DIR"
  mv -- "$TARGET_DIR" "$REMOVED_DIR"
  na_info "MODULE_REMOVED_FROM_SCAN_PATH=$TARGET_DIR"
  na_info "MODULE_PRESERVED=$REMOVED_DIR"
fi

na_info 'SERVICE_RESTARTS=NONE'
na_info 'PASS'

#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck source=lib/network-utilization-common.sh
source "$SCRIPT_DIR/lib/network-utilization-common.sh"
[[ $# -eq 2 && $1 == --confirm-module-disabled && ( $2 == --restore-latest || $2 == --remove-current ) ]] || nu_fail 'usage: rollback-network-utilization.sh --confirm-module-disabled (--restore-latest|--remove-current)'
nu_require_root; nu_validate_environment; TARGET="$NU_MODULES_DIR/NetworkUtilization"; [[ -d "$TARGET" ]] || nu_fail 'installed module not found'; STAMP=$(date -u +%Y%m%d-%H%M%S)
if [[ $2 == --restore-latest ]]; then NAME=$(find "$NU_MODULES_DIR" -mindepth 1 -maxdepth 1 -type d -name 'NetworkUtilization.backup-*' -printf '%f\n' | LC_ALL=C sort | tail -n1); [[ -n "$NAME" ]] || nu_fail 'no module backup is available'; nu_validate_release "$NU_MODULES_DIR/$NAME"; REPLACED="$NU_MODULES_DIR/NetworkUtilization.rollback-replaced-$STAMP"; mv "$TARGET" "$REPLACED"; mv "$NU_MODULES_DIR/$NAME" "$TARGET" || { mv "$REPLACED" "$TARGET" || true; nu_fail 'restore failed'; }; nu_info "RESTORED_FROM=$NAME"; nu_info "REPLACED_MODULE_PRESERVED=$REPLACED";
else REMOVED="$NU_MODULES_DIR/NetworkUtilization.removed-$STAMP"; mv "$TARGET" "$REMOVED"; nu_info "MODULE_PRESERVED=$REMOVED"; fi
nu_info "RUNTIME_CONFIGURATION=PRESERVED:${NETWORK_UTILIZATION_RUNTIME_DIR:-/var/lib/zabbix/network-utilization}"; nu_info 'SERVICE_RESTARTS=NONE'; nu_info PASS

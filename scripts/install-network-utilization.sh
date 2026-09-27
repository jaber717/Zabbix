#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P); REPO_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd -P)
# shellcheck source=lib/network-utilization-common.sh
source "$SCRIPT_DIR/lib/network-utilization-common.sh"
SOURCE_DIR="$REPO_ROOT/frontend/modules/NetworkUtilization"; RUNTIME_DIR=${NETWORK_UTILIZATION_RUNTIME_DIR:-/var/lib/zabbix/network-utilization}; PREFLIGHT=0
if [[ ${1:-} == --preflight && $# -eq 1 ]]; then PREFLIGHT=1; elif [[ $# -ne 0 ]]; then nu_fail 'usage: install-network-utilization.sh [--preflight]'; fi
nu_validate_environment; nu_validate_release "$SOURCE_DIR"; TARGET="$NU_MODULES_DIR/NetworkUtilization"
nu_info "OS=$NU_OS_NAME"; nu_info "ZABBIX_VERSION=$NU_ZABBIX_VERSION"; nu_info "PHP_VERSION=$NU_PHP_VERSION"; nu_info "MODULES_DIR=$NU_MODULES_DIR"; nu_info "RELEASE=$NU_MODULE_VERSION"
(( PREFLIGHT )) && { nu_info 'PREFLIGHT=PASS'; exit 0; }
nu_require_root; nu_require_command getent; nu_detect_php_fpm_identity
install -d -o root -g root -m 0755 "$(dirname -- "$RUNTIME_DIR")"; install -d -o "$NU_RUNTIME_USER" -g "$NU_RUNTIME_GROUP" -m 0750 "$RUNTIME_DIR"
RUNTIME_CONFIG="$RUNTIME_DIR/link-definitions.json"; RUNTIME_BACKUP="$RUNTIME_DIR/link-definitions.last-known-good.json"
if [[ -r "$RUNTIME_CONFIG" ]]; then nu_validate_config "$RUNTIME_CONFIG" "$SOURCE_DIR"; chown "$NU_RUNTIME_USER:$NU_RUNTIME_GROUP" "$RUNTIME_CONFIG"; chmod 0640 "$RUNTIME_CONFIG"; nu_info 'RUNTIME_CONFIGURATION=PRESERVED';
else temp=$(mktemp "$RUNTIME_DIR/.link-definitions.XXXXXX"); cp -- "$SOURCE_DIR/config/link-definitions.json" "$temp"; chown "$NU_RUNTIME_USER:$NU_RUNTIME_GROUP" "$temp"; chmod 0640 "$temp"; mv -- "$temp" "$RUNTIME_CONFIG"; nu_info 'RUNTIME_CONFIGURATION=INITIALIZED'; fi
if [[ ! -r "$RUNTIME_BACKUP" ]]; then cp -- "$RUNTIME_CONFIG" "$RUNTIME_BACKUP"; chown "$NU_RUNTIME_USER:$NU_RUNTIME_GROUP" "$RUNTIME_BACKUP"; chmod 0640 "$RUNTIME_BACKUP"; fi
if command -v selinuxenabled >/dev/null 2>&1 && selinuxenabled; then nu_require_command semanage; nu_require_command restorecon; semanage fcontext -a -t httpd_sys_rw_content_t "$RUNTIME_DIR(/.*)?" 2>/dev/null || semanage fcontext -m -t httpd_sys_rw_content_t "$RUNTIME_DIR(/.*)?"; restorecon -RF "$RUNTIME_DIR"; fi
if [[ -d "$TARGET" && -r "$TARGET/VERSION" && $(tr -d '[:space:]' < "$TARGET/VERSION") == "$NU_MODULE_VERSION" ]] && nu_validate_release "$TARGET" >/dev/null 2>&1 && cmp -s "$SOURCE_DIR/RELEASE.sha256" "$TARGET/RELEASE.sha256"; then nu_info "ALREADY_INSTALLED=$NU_MODULE_VERSION"; nu_info PASS; exit 0; fi
[[ ! -e "$TARGET" || -d "$TARGET" ]] || nu_fail "module target is not a directory: $TARGET"
OWNER=$(stat -c %U "${TARGET:-$NU_MODULES_DIR}" 2>/dev/null || stat -c %U "$NU_MODULES_DIR"); GROUP=$(stat -c %G "${TARGET:-$NU_MODULES_DIR}" 2>/dev/null || stat -c %G "$NU_MODULES_DIR")
STAGE=$(mktemp -d "$NU_MODULES_DIR/.NetworkUtilization.install.XXXXXX"); trap '[[ -n ${STAGE:-} && -d $STAGE ]] && rm -rf -- "$STAGE"' EXIT
cp -a "$SOURCE_DIR/." "$STAGE/"; chown -R "$OWNER:$GROUP" "$STAGE"; find "$STAGE" -type d -exec chmod 0755 {} +; find "$STAGE" -type f -exec chmod 0644 {} +; nu_validate_release "$STAGE"
STAMP=$(date -u +%Y%m%d-%H%M%S); BACKUP=''; if [[ -d "$TARGET" ]]; then BACKUP="$NU_MODULES_DIR/NetworkUtilization.backup-$STAMP"; mv "$TARGET" "$BACKUP"; fi
if ! mv "$STAGE" "$TARGET"; then [[ -n "$BACKUP" && -d "$BACKUP" ]] && mv "$BACKUP" "$TARGET" || true; nu_fail 'activation failed; previous module restoration was attempted'; fi; STAGE=''
if command -v selinuxenabled >/dev/null 2>&1 && selinuxenabled; then restorecon -RF "$TARGET"; fi
nu_validate_release "$TARGET"; nu_info "INSTALLED=$TARGET"; nu_info "RUNTIME_CONFIG=$RUNTIME_CONFIG"; nu_info 'SERVICE_RESTARTS=NONE'; nu_info PASS

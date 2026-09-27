#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck source=lib/network-utilization-common.sh
source "$SCRIPT_DIR/lib/network-utilization-common.sh"
[[ $# -eq 0 ]] || nu_fail 'usage: verify-network-utilization.sh'
nu_validate_environment; TARGET="$NU_MODULES_DIR/NetworkUtilization"; nu_validate_release "$TARGET"; nu_detect_php_fpm_identity
RUNTIME=${NETWORK_UTILIZATION_RUNTIME_DIR:-/var/lib/zabbix/network-utilization}; CONFIG="$RUNTIME/link-definitions.json"
[[ $(stat -c %U:%G "$RUNTIME") == "$NU_RUNTIME_USER:$NU_RUNTIME_GROUP" && $(stat -c %a "$RUNTIME") == 750 ]] || nu_fail 'runtime directory ownership/mode mismatch'
[[ -r "$CONFIG" && $(stat -c %U:%G "$CONFIG") == "$NU_RUNTIME_USER:$NU_RUNTIME_GROUP" && $(stat -c %a "$CONFIG") == 640 ]] || nu_fail 'runtime configuration ownership/mode mismatch'
nu_validate_config "$CONFIG" "$TARGET"
if command -v selinuxenabled >/dev/null 2>&1 && selinuxenabled; then find "$TARGET" -exec ls -Zd -- {} + | grep -qv ':usr_t:' && nu_fail 'module SELinux type must be usr_t'; ls -Zd "$RUNTIME" | grep -q httpd_sys_rw_content_t || nu_fail 'runtime SELinux type mismatch'; fi
nu_info "OS=$NU_OS_NAME"; nu_info "ZABBIX_VERSION=$NU_ZABBIX_VERSION"; nu_info "PHP_VERSION=$NU_PHP_VERSION"; nu_info "MODULE_PATH=$TARGET"; nu_info "MODULE_RELEASE=$NU_MODULE_VERSION"; nu_info "RUNTIME_CONFIG=$CONFIG"; nu_info 'CHECKSUMS=PASS'; nu_info 'PHP_SYNTAX=PASS'; nu_info 'RUNTIME_CONFIGURATION=PASS'; nu_info PASS

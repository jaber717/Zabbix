#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck source=lib/network-availability-common.sh
source "$SCRIPT_DIR/lib/network-availability-common.sh"

[[ $# -eq 0 ]] || na_fail 'usage: verify-network-availability.sh'

na_validate_environment
TARGET_DIR="$NA_MODULES_DIR/NetworkAvailability"
na_validate_release_module "$TARGET_DIR"
RUNTIME_DIR=${NETWORK_AVAILABILITY_RUNTIME_DIR:-/var/lib/zabbix/network-availability}
RUNTIME_CONFIG="$RUNTIME_DIR/node-definitions.json"
na_detect_php_fpm_identity
[[ -d "$RUNTIME_DIR" ]] || na_fail "runtime configuration directory is missing: $RUNTIME_DIR"
[[ $(stat -c '%U:%G' "$RUNTIME_DIR") == "$NA_RUNTIME_USER:$NA_RUNTIME_GROUP" ]] \
	|| na_fail "runtime directory ownership must be $NA_RUNTIME_USER:$NA_RUNTIME_GROUP"
[[ $(stat -c '%a' "$RUNTIME_DIR") == '750' ]] || na_fail 'runtime directory mode must be 750'
[[ -r "$RUNTIME_CONFIG" ]] || na_fail "runtime configuration is missing: $RUNTIME_CONFIG"
[[ $(stat -c '%U:%G' "$RUNTIME_CONFIG") == "$NA_RUNTIME_USER:$NA_RUNTIME_GROUP" ]] \
	|| na_fail "runtime configuration ownership must be $NA_RUNTIME_USER:$NA_RUNTIME_GROUP"
[[ $(stat -c '%a' "$RUNTIME_CONFIG") == '640' ]] || na_fail 'runtime configuration mode must be 640'
na_validate_node_config "$RUNTIME_CONFIG"
if command -v selinuxenabled >/dev/null 2>&1 && selinuxenabled; then
	if find "$TARGET_DIR" -exec ls -Zd -- {} + | grep -qv ':usr_t:'; then
		na_fail 'installed module SELinux type must be usr_t'
	fi
	ls -Zd "$RUNTIME_DIR" | grep -q 'httpd_sys_rw_content_t' \
		|| na_fail 'runtime directory SELinux type must be httpd_sys_rw_content_t'
fi

UNREADABLE=$(find "$TARGET_DIR" -type f ! -readable -print -quit)
[[ -z "$UNREADABLE" ]] || na_fail "installed file is unreadable: $UNREADABLE"

na_info "OS=$NA_OS_NAME"
na_info "ZABBIX_VERSION=$NA_ZABBIX_VERSION"
na_info "PHP_VERSION=$NA_PHP_VERSION"
na_info "MODULE_PATH=$TARGET_DIR"
na_info "MODULE_RELEASE=$NA_MODULE_VERSION"
na_info "RUNTIME_CONFIG=$RUNTIME_CONFIG"
na_info "RUNTIME_OWNER=$NA_RUNTIME_USER:$NA_RUNTIME_GROUP"
na_info "OWNER=$(stat -c '%U:%G' "$TARGET_DIR")"
na_info "MODE=$(stat -c '%a' "$TARGET_DIR")"
na_info 'MANIFEST=PASS'
na_info 'CHECKSUMS=PASS'
na_info 'PHP_SYNTAX=PASS'
na_info 'RUNTIME_CONFIGURATION=PASS'
na_info 'PASS'

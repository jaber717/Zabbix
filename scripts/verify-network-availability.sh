#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck source=lib/network-availability-common.sh
source "$SCRIPT_DIR/lib/network-availability-common.sh"

[[ $# -eq 0 ]] || na_fail 'usage: verify-network-availability.sh'

na_validate_environment
TARGET_DIR="$NA_MODULES_DIR/NetworkAvailability"
na_validate_release_module "$TARGET_DIR"

UNREADABLE=$(find "$TARGET_DIR" -type f ! -readable -print -quit)
[[ -z "$UNREADABLE" ]] || na_fail "installed file is unreadable: $UNREADABLE"

na_info "OS=$NA_OS_NAME"
na_info "ZABBIX_VERSION=$NA_ZABBIX_VERSION"
na_info "PHP_VERSION=$NA_PHP_VERSION"
na_info "MODULE_PATH=$TARGET_DIR"
na_info "MODULE_RELEASE=$NA_MODULE_VERSION"
na_info "OWNER=$(stat -c '%U:%G' "$TARGET_DIR")"
na_info "MODE=$(stat -c '%a' "$TARGET_DIR")"
na_info 'MANIFEST=PASS'
na_info 'CHECKSUMS=PASS'
na_info 'PHP_SYNTAX=PASS'
na_info 'NODE_CONFIGURATION_SCHEMA=PASS'
na_info 'PASS'

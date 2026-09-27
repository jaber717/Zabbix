#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
REPO_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd -P)
# shellcheck source=lib/network-availability-common.sh
source "$SCRIPT_DIR/lib/network-availability-common.sh"

SOURCE_DIR="$REPO_ROOT/frontend/modules/NetworkAvailability"
RUNTIME_DIR=${NETWORK_AVAILABILITY_RUNTIME_DIR:-/var/lib/zabbix/network-availability}
PREFLIGHT_ONLY=0
if [[ ${1:-} == '--preflight' && $# -eq 1 ]]; then
  PREFLIGHT_ONLY=1
elif [[ $# -ne 0 ]]; then
  na_fail 'usage: install-network-availability.sh [--preflight]'
fi

na_validate_environment
na_require_command cmp
na_validate_release_module "$SOURCE_DIR"

TARGET_DIR="$NA_MODULES_DIR/NetworkAvailability"
na_info "OS=$NA_OS_NAME"
na_info "ZABBIX_VERSION=$NA_ZABBIX_VERSION"
na_info "PHP_VERSION=$NA_PHP_VERSION"
na_info "FRONTEND_ROOT=$NA_FRONTEND_ROOT"
na_info "MODULES_DIR=$NA_MODULES_DIR"
na_info "RELEASE=$NA_MODULE_VERSION"

if (( PREFLIGHT_ONLY )); then
  na_info 'PREFLIGHT=PASS'
  exit 0
fi

na_require_root
[[ -w "$NA_MODULES_DIR" ]] || na_fail "module directory is not writable: $NA_MODULES_DIR"

na_require_command getent
na_detect_php_fpm_identity
RUNTIME_PARENT=$(dirname -- "$RUNTIME_DIR")
install -d -o root -g root -m 0755 "$RUNTIME_PARENT"
install -d -o "$NA_RUNTIME_USER" -g "$NA_RUNTIME_GROUP" -m 0750 "$RUNTIME_DIR"
RUNTIME_CONFIG="$RUNTIME_DIR/node-definitions.json"
RUNTIME_BACKUP="$RUNTIME_DIR/node-definitions.last-known-good.json"
if [[ -r "$RUNTIME_CONFIG" ]]; then
	na_validate_node_config "$RUNTIME_CONFIG"
	chown -- "$NA_RUNTIME_USER:$NA_RUNTIME_GROUP" "$RUNTIME_CONFIG"
	chmod 0640 "$RUNTIME_CONFIG"
	na_info 'RUNTIME_CONFIGURATION=PRESERVED'
else
	CONFIG_SOURCE="$SOURCE_DIR/config/node-definitions.json"
	if [[ -d "$TARGET_DIR" && -r "$TARGET_DIR/config/node-definitions.json" ]]; then
		CONFIG_SOURCE="$TARGET_DIR/config/node-definitions.json"
	fi
	RUNTIME_TEMP=$(mktemp "$RUNTIME_DIR/.node-definitions.XXXXXX")
	"$NA_PHP_BIN" -r '
		require $argv[1];
		$repository = new Modules\NetworkAvailability\Config\NodeDefinitionRepository($argv[2]);
		echo json_encode($repository->loadDocument(), JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR), "\n";
	' "$SOURCE_DIR/config/NodeDefinitionRepository.php" "$CONFIG_SOURCE" > "$RUNTIME_TEMP"
	chown -- "$NA_RUNTIME_USER:$NA_RUNTIME_GROUP" "$RUNTIME_TEMP"
	chmod 0640 "$RUNTIME_TEMP"
	mv -- "$RUNTIME_TEMP" "$RUNTIME_CONFIG"
	na_info "RUNTIME_CONFIGURATION=INITIALIZED_FROM:$CONFIG_SOURCE"
fi
if [[ ! -r "$RUNTIME_BACKUP" ]]; then
	cp -- "$RUNTIME_CONFIG" "$RUNTIME_BACKUP"
	chown -- "$NA_RUNTIME_USER:$NA_RUNTIME_GROUP" "$RUNTIME_BACKUP"
	chmod 0640 "$RUNTIME_BACKUP"
fi
if command -v selinuxenabled >/dev/null 2>&1 && selinuxenabled; then
	na_require_command semanage
	na_require_command restorecon
	semanage fcontext -a -t httpd_sys_rw_content_t "$RUNTIME_DIR(/.*)?" 2>/dev/null \
		|| semanage fcontext -m -t httpd_sys_rw_content_t "$RUNTIME_DIR(/.*)?"
	restorecon -RF "$RUNTIME_DIR"
fi

if [[ -d "$TARGET_DIR" && -r "$TARGET_DIR/VERSION" \
    && $(tr -d '[:space:]' < "$TARGET_DIR/VERSION") == "$NA_MODULE_VERSION" ]]; then
  if (na_validate_release_module "$TARGET_DIR") >/dev/null 2>&1 \
      && cmp -s -- "$SOURCE_DIR/RELEASE.sha256" "$TARGET_DIR/RELEASE.sha256"; then
    if command -v selinuxenabled >/dev/null 2>&1 && selinuxenabled; then
      restorecon -RF "$TARGET_DIR"
    fi
    na_info "ALREADY_INSTALLED=$NA_MODULE_VERSION"
    na_info 'PASS'
    exit 0
  fi
  na_info 'Existing same-version installation differs from this release or failed integrity checks; replacing it.'
fi

if [[ -e "$TARGET_DIR" && ! -d "$TARGET_DIR" ]]; then
  na_fail "module target exists but is not a directory: $TARGET_DIR"
fi

if [[ -d "$TARGET_DIR" ]]; then
  na_validate_existing_module_for_upgrade "$TARGET_DIR"
fi

REFERENCE_DIR=$NA_MODULES_DIR
if [[ -d "$TARGET_DIR" ]]; then
  REFERENCE_DIR=$TARGET_DIR
fi
OWNER=$(stat -c '%U' "$REFERENCE_DIR")
GROUP=$(stat -c '%G' "$REFERENCE_DIR")
[[ -n "$OWNER" && -n "$GROUP" ]] || na_fail 'unable to determine module ownership convention'

STAGE_DIR=$(mktemp -d "$NA_MODULES_DIR/.NetworkAvailability.install.XXXXXX")
cleanup_stage() {
  if [[ -n ${STAGE_DIR:-} && -d "$STAGE_DIR" ]]; then
    rm -rf -- "$STAGE_DIR"
  fi
}
trap cleanup_stage EXIT

cp -a -- "$SOURCE_DIR/." "$STAGE_DIR/"

chown -R -- "$OWNER:$GROUP" "$STAGE_DIR"
find "$STAGE_DIR" -type d -exec chmod 0755 {} +
find "$STAGE_DIR" -type f -exec chmod 0644 {} +
na_validate_release_module "$STAGE_DIR"

TIMESTAMP=$(date -u +%Y%m%d-%H%M%S)
BACKUP_DIR=''
if [[ -d "$TARGET_DIR" ]]; then
  BACKUP_DIR="$NA_MODULES_DIR/NetworkAvailability.backup-$TIMESTAMP"
  [[ ! -e "$BACKUP_DIR" ]] || na_fail "backup path already exists: $BACKUP_DIR"
  mv -- "$TARGET_DIR" "$BACKUP_DIR"
fi

if ! mv -- "$STAGE_DIR" "$TARGET_DIR"; then
  if [[ -n "$BACKUP_DIR" && -d "$BACKUP_DIR" && ! -e "$TARGET_DIR" ]]; then
    mv -- "$BACKUP_DIR" "$TARGET_DIR" || true
  fi
  na_fail 'failed to activate the staged module; previous module restoration was attempted'
fi
STAGE_DIR=''

if command -v selinuxenabled >/dev/null 2>&1 && selinuxenabled; then
  restorecon -RF "$TARGET_DIR"
fi

if ! (na_validate_release_module "$TARGET_DIR") >/dev/null 2>&1; then
  FAILED_DIR="$NA_MODULES_DIR/NetworkAvailability.failed-$TIMESTAMP"
  mv -- "$TARGET_DIR" "$FAILED_DIR" || true
  if [[ -n "$BACKUP_DIR" && -d "$BACKUP_DIR" ]]; then
    mv -- "$BACKUP_DIR" "$TARGET_DIR" || true
  fi
  na_fail "post-install validation failed; failed files preserved at $FAILED_DIR"
fi

na_info "INSTALLED=$TARGET_DIR"
na_info "OWNER=$OWNER:$GROUP"
na_info "RUNTIME_CONFIG=$RUNTIME_CONFIG"
na_info "RUNTIME_OWNER=$NA_RUNTIME_USER:$NA_RUNTIME_GROUP"
if [[ -n "$BACKUP_DIR" ]]; then
  na_info "BACKUP=$BACKUP_DIR"
else
  na_info 'BACKUP=NONE (first installation)'
fi
na_info 'SERVICE_RESTARTS=NONE'
na_info 'PASS'

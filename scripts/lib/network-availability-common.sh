#!/usr/bin/env bash

na_fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

na_info() {
  printf '%s\n' "$*"
}

na_require_command() {
  command -v "$1" >/dev/null 2>&1 || na_fail "required command not found: $1"
}

na_require_root() {
  [[ ${EUID:-$(id -u)} -eq 0 ]] || na_fail 'run this command as root (for example, with sudo)'
}

na_detect_os() {
  local os_release=${NETWORK_AVAILABILITY_OS_RELEASE:-/etc/os-release}
  [[ -r "$os_release" ]] || na_fail "cannot read OS release file: $os_release"

  local ID='' VERSION_ID='' PRETTY_NAME=''
  # shellcheck disable=SC1090
  source "$os_release"
  [[ "$ID" == 'rhel' ]] || na_fail "unsupported OS: ${PRETTY_NAME:-$ID}; RHEL 9 is required"
  [[ "${VERSION_ID%%.*}" == '9' ]] || na_fail "unsupported RHEL release: $VERSION_ID; RHEL 9 is required"
  NA_OS_NAME=${PRETTY_NAME:-"RHEL $VERSION_ID"}
}

na_detect_frontend() {
  local candidate
  local -a candidates=()

  if [[ -n ${ZABBIX_FRONTEND_ROOT:-} ]]; then
    candidates+=("$ZABBIX_FRONTEND_ROOT")
  else
    candidates+=(/usr/share/zabbix /usr/share/zabbix/ui)
  fi

  for candidate in "${candidates[@]}"; do
    if [[ -d "$candidate" && -d "$candidate/modules" && -r "$candidate/include/defines.inc.php" ]]; then
      NA_FRONTEND_ROOT=$(cd -- "$candidate" && pwd -P)
      NA_MODULES_DIR="$NA_FRONTEND_ROOT/modules"
      return 0
    fi
  done

  na_fail 'Zabbix frontend not found; checked for a frontend root with modules/ and include/defines.inc.php'
}

na_detect_zabbix_version() {
  local defines_file="$NA_FRONTEND_ROOT/include/defines.inc.php"
  local version=''

  version=$(sed -nE "s/.*define\(['\"]ZABBIX_VERSION['\"],[[:space:]]*['\"]([^'\"]+)['\"]\).*/\1/p" "$defines_file" | head -n 1)
  if [[ -z "$version" ]] && command -v rpm >/dev/null 2>&1; then
    version=$(rpm -qa --qf '%{NAME}\t%{VERSION}\n' | awk -F '\t' '$1 ~ /^zabbix-web/ {print $2; exit}')
  fi
  [[ -n "$version" ]] || na_fail 'unable to determine Zabbix frontend version'
  [[ "$version" =~ ^7\.0\.[0-9]+([.-].*)?$ ]] || na_fail "unsupported Zabbix version: $version; Zabbix 7.0.x is required"
  NA_ZABBIX_VERSION=$version
}

na_detect_php() {
  NA_PHP_BIN=${PHP_BIN:-php}
  na_require_command "$NA_PHP_BIN"
  local version
  version=$("$NA_PHP_BIN" -r 'echo PHP_MAJOR_VERSION.".".PHP_MINOR_VERSION.".".PHP_RELEASE_VERSION;') \
    || na_fail 'unable to execute PHP'
  [[ "$version" =~ ^8\.([1-9]|[1-9][0-9])\.[0-9]+([.-].*)?$ ]] \
    || na_fail "unsupported PHP version: $version; PHP 8.1 or newer in the PHP 8 series is required"
  NA_PHP_VERSION=$version
}

na_validate_environment() {
  na_require_command find
  na_require_command sha256sum
  na_require_command stat
  na_detect_os
  na_detect_frontend
  na_detect_zabbix_version
  na_detect_php
}

na_validate_checksum_manifest() {
  local module_dir=$1
  local checksum_file="$module_dir/RELEASE.sha256"
  [[ -r "$checksum_file" ]] || na_fail "release checksum manifest is missing: $checksum_file"

  local checksum path
  while read -r checksum path; do
    [[ "$checksum" =~ ^[0-9a-f]{64}$ ]] || na_fail 'invalid SHA256 entry in RELEASE.sha256'
    path=${path#\*}
    [[ -n "$path" && "$path" != /* && "$path" != *'..'* ]] \
      || na_fail "unsafe path in RELEASE.sha256: $path"
  done < "$checksum_file"

  (cd -- "$module_dir" && sha256sum --quiet -c RELEASE.sha256) \
    || na_fail "release checksum validation failed: $module_dir"
}

na_manifest_version() {
  local manifest=$1
  "$NA_PHP_BIN" -r '
    $data = json_decode(file_get_contents($argv[1]), true, 32, JSON_THROW_ON_ERROR);
    echo $data["version"] ?? "";
  ' "$manifest"
}

na_validate_node_config() {
  local config=$1
  "$NA_PHP_BIN" -r '
    $data = json_decode(file_get_contents($argv[1]), true, 32, JSON_THROW_ON_ERROR);
    if (($data["schema"] ?? null) !== "network-availability-node-definitions-v1"
        || !is_array($data["nodes"] ?? null)) {
      fwrite(STDERR, "invalid Node definition schema\n");
      exit(1);
    }
  ' "$config" || na_fail "invalid Node definition file: $config"
}

na_validate_module_structure() {
  local module_dir=$1
  local required
  local -a required_files=(
    manifest.json Widget.php actions/WidgetView.php
    assets/css/network-availability.css assets/js/class.widget.js
    collector/AvailabilityCollectorInterface.php collector/ZabbixAvailabilityCollector.php
    config/Limits.php config/NodeDefinitionRepository.php config/node-definitions.json
    domain/AvailabilityResolver.php domain/ExpectedIntervalResolver.php
    views/widget.view.php
  )

  [[ -d "$module_dir" ]] || na_fail "module directory does not exist: $module_dir"
  for required in "${required_files[@]}"; do
    [[ -f "$module_dir/$required" && -r "$module_dir/$required" ]] \
      || na_fail "required module file is missing or unreadable: $required"
  done
  local nested_dir
  while IFS= read -r nested_dir; do
    case "$nested_dir" in
      Collector|Config|Domain)
        na_fail 'uppercase nested module directories are unsupported on the target filesystem'
        ;;
    esac
  done < <(find "$module_dir" -mindepth 1 -maxdepth 1 -type d -printf '%f\n')
  [[ -z $(find "$module_dir" -type l -print -quit) ]] || na_fail 'symbolic links are not allowed in the module directory'
  na_validate_node_config "$module_dir/config/node-definitions.json"
}

na_lint_module_php() {
  local module_dir=$1
  local file
  while IFS= read -r -d '' file; do
    "$NA_PHP_BIN" -l "$file" >/dev/null || na_fail "PHP syntax check failed: $file"
  done < <(find "$module_dir" -type f -name '*.php' -print0)
}

na_validate_release_module() {
  local module_dir=$1
  na_validate_module_structure "$module_dir"
  [[ -r "$module_dir/VERSION" ]] || na_fail "VERSION marker is missing: $module_dir"
  local version manifest_version
  version=$(tr -d '[:space:]' < "$module_dir/VERSION")
  [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || na_fail "invalid VERSION marker: $version"
  manifest_version=$(na_manifest_version "$module_dir/manifest.json") \
    || na_fail 'unable to read the module manifest version'
  [[ "$manifest_version" == "$version" ]] \
    || na_fail "manifest version $manifest_version does not match VERSION $version"
  na_validate_checksum_manifest "$module_dir"
  na_lint_module_php "$module_dir"
  NA_MODULE_VERSION=$version
}

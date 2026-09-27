#!/usr/bin/env bash

nu_fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
nu_info() { printf '%s\n' "$*"; }
nu_require_command() { command -v "$1" >/dev/null 2>&1 || nu_fail "required command not found: $1"; }
nu_require_root() { [[ ${EUID:-$(id -u)} -eq 0 ]] || nu_fail 'run this command as root (for example, with sudo)'; }

nu_detect_os() {
	local file=${NETWORK_UTILIZATION_OS_RELEASE:-/etc/os-release} ID='' VERSION_ID='' PRETTY_NAME=''
	[[ -r "$file" ]] || nu_fail "cannot read OS release file: $file"
	# shellcheck disable=SC1090
	source "$file"
	[[ "$ID" == rhel && "${VERSION_ID%%.*}" == 9 ]] || nu_fail "RHEL 9 is required; found ${PRETTY_NAME:-$ID}"
	NU_OS_NAME=${PRETTY_NAME:-"RHEL $VERSION_ID"}
}

nu_detect_frontend() {
	local candidate; local -a candidates=()
	if [[ -n ${ZABBIX_FRONTEND_ROOT:-} ]]; then candidates+=("$ZABBIX_FRONTEND_ROOT"); else candidates+=(/usr/share/zabbix /usr/share/zabbix/ui); fi
	for candidate in "${candidates[@]}"; do
		if [[ -d "$candidate/modules" && -r "$candidate/include/defines.inc.php" ]]; then NU_FRONTEND_ROOT=$(cd -- "$candidate" && pwd -P); NU_MODULES_DIR="$NU_FRONTEND_ROOT/modules"; return; fi
	done
	nu_fail 'Zabbix frontend root with modules/ and include/defines.inc.php was not found'
}

nu_detect_zabbix() {
	NU_ZABBIX_VERSION=$(sed -nE "s/.*define\(['\"]ZABBIX_VERSION['\"],[[:space:]]*['\"]([^'\"]+)['\"]\).*/\1/p" "$NU_FRONTEND_ROOT/include/defines.inc.php" | head -n1)
	[[ "$NU_ZABBIX_VERSION" =~ ^7\.0\.[0-9]+([.-].*)?$ ]] || nu_fail "Zabbix 7.0.x is required; found ${NU_ZABBIX_VERSION:-unknown}"
}

nu_detect_php() {
	NU_PHP_BIN=${PHP_BIN:-php}; nu_require_command "$NU_PHP_BIN"
	NU_PHP_VERSION=$($NU_PHP_BIN -r 'echo PHP_MAJOR_VERSION.".".PHP_MINOR_VERSION.".".PHP_RELEASE_VERSION;') || nu_fail 'unable to run PHP'
	[[ "$NU_PHP_VERSION" =~ ^8\.([1-9]|[1-9][0-9])\.[0-9]+ ]] || nu_fail "PHP 8.1+ is required; found $NU_PHP_VERSION"
}

nu_validate_environment() { nu_require_command find; nu_require_command sha256sum; nu_require_command stat; nu_detect_os; nu_detect_frontend; nu_detect_zabbix; nu_detect_php; }

nu_validate_config() {
	local file=$1 module=$2
	"$NU_PHP_BIN" -r '
		require $argv[1]; require $argv[2];
		$data=json_decode(file_get_contents($argv[3]),true,64,JSON_THROW_ON_ERROR);
		Modules\NetworkUtilization\Config\LinkDefinitionRepository::validateDocument($data);
	' "$module/config/Limits.php" "$module/config/LinkDefinitionRepository.php" "$file" || nu_fail "invalid Link definition file: $file"
}

nu_validate_checksums() {
	local module=$1 checksum path
	[[ -r "$module/RELEASE.sha256" ]] || nu_fail "missing RELEASE.sha256: $module"
	while read -r checksum path; do path=${path#\*}; [[ "$checksum" =~ ^[0-9a-f]{64}$ && -n "$path" && "$path" != /* && "$path" != *..* ]] || nu_fail "unsafe checksum entry: $path"; done < "$module/RELEASE.sha256"
	(cd -- "$module" && sha256sum --quiet -c RELEASE.sha256) || nu_fail "release checksum validation failed: $module"
}

nu_validate_structure() {
	local module=$1 file; local -a required=(manifest.json Widget.php VERSION actions/WidgetView.php actions/ConfigUpdate.php assets/css/network-utilization.css assets/js/class.widget.js collector/LinkUtilizationCollectorInterface.php collector/ZabbixLinkUtilizationCollector.php config/Limits.php config/LinkDefinitionRepository.php config/link-definitions.json domain/LinkUtilizationResolver.php views/widget.view.php)
	[[ -d "$module" ]] || nu_fail "module directory missing: $module"
	for file in "${required[@]}"; do [[ -r "$module/$file" ]] || nu_fail "required file missing: $file"; done
	[[ -z $(find "$module" -type l -print -quit) ]] || nu_fail 'symbolic links are not allowed in the module'
	nu_validate_config "$module/config/link-definitions.json" "$module"
}

nu_validate_release() {
	local module=$1 file version manifest_version
	nu_validate_structure "$module"; version=$(tr -d '[:space:]' < "$module/VERSION"); [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || nu_fail "invalid VERSION: $version"
	manifest_version=$($NU_PHP_BIN -r '$d=json_decode(file_get_contents($argv[1]),true,32,JSON_THROW_ON_ERROR);echo $d["version"]??"";' "$module/manifest.json")
	[[ "$manifest_version" == "$version" ]] || nu_fail 'manifest and VERSION differ'
	nu_validate_checksums "$module"
	while IFS= read -r -d '' file; do "$NU_PHP_BIN" -l "$file" >/dev/null || nu_fail "PHP syntax failed: $file"; done < <(find "$module" -type f -name '*.php' -print0)
	NU_MODULE_VERSION=$version
}

nu_detect_php_fpm_identity() {
	local pool=${NETWORK_UTILIZATION_PHP_FPM_POOL:-/etc/php-fpm.d/www.conf}
	NU_RUNTIME_USER=${NETWORK_UTILIZATION_RUNTIME_USER:-$(sed -nE 's/^[[:space:]]*user[[:space:]]*=[[:space:]]*([^[:space:];]+).*/\1/p' "$pool" | head -n1)}
	NU_RUNTIME_GROUP=${NETWORK_UTILIZATION_RUNTIME_GROUP:-$(sed -nE 's/^[[:space:]]*group[[:space:]]*=[[:space:]]*([^[:space:];]+).*/\1/p' "$pool" | head -n1)}
	getent passwd "$NU_RUNTIME_USER" >/dev/null && getent group "$NU_RUNTIME_GROUP" >/dev/null || nu_fail 'unable to determine PHP-FPM identity'
}

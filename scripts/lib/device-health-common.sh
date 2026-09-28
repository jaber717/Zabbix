#!/usr/bin/env bash
dh_fail(){ printf 'FAIL: %s\n' "$*" >&2; exit 1; }
dh_info(){ printf '%s\n' "$*"; }
dh_need(){ command -v "$1" >/dev/null 2>&1 || dh_fail "required command not found: $1"; }
dh_root(){ [[ ${EUID:-$(id -u)} -eq 0 ]] || dh_fail 'run as root (for example, with sudo)'; }
dh_environment(){
	local file=${DEVICE_HEALTH_OS_RELEASE:-/etc/os-release} ID='' VERSION_ID='' PRETTY_NAME=''; [[ -r $file ]]||dh_fail 'cannot read OS release'; source "$file";
	[[ $ID == rhel && ${VERSION_ID%%.*} == 9 ]]||dh_fail "RHEL 9 required; found ${PRETTY_NAME:-$ID}"; DH_OS=${PRETTY_NAME:-RHEL};
	local c; for c in ${ZABBIX_FRONTEND_ROOT:-} /usr/share/zabbix /usr/share/zabbix/ui; do [[ -n $c && -d $c/modules && -r $c/include/defines.inc.php ]]&&{ DH_ROOT=$(cd "$c"&&pwd -P);DH_MODULES=$DH_ROOT/modules;break;};done
	[[ -n ${DH_ROOT:-} ]]||dh_fail 'Zabbix frontend not found'; DH_ZABBIX=$(sed -nE "s/.*define\(['\"]ZABBIX_VERSION['\"],[[:space:]]*['\"]([^'\"]+)['\"]\).*/\1/p" "$DH_ROOT/include/defines.inc.php"|head -n1); [[ $DH_ZABBIX =~ ^7\.0\. ]]||dh_fail "Zabbix 7.0.x required; found $DH_ZABBIX";
	DH_PHP=${PHP_BIN:-php}; DH_PHP_VERSION=$($DH_PHP -r 'echo PHP_VERSION;')||dh_fail 'PHP unavailable'; [[ $DH_PHP_VERSION =~ ^8\. ]]||dh_fail 'PHP 8 required';
}
dh_config(){ "$DH_PHP" -r 'require $argv[1];$d=json_decode(file_get_contents($argv[2]),true,64,JSON_THROW_ON_ERROR);Modules\DeviceHealth\Config\HealthConfigRepository::validate($d);' "$1/config/HealthConfigRepository.php" "$2"||dh_fail 'invalid Device Health configuration'; }
dh_release(){
	local m=$1 f v mv; for f in manifest.json Widget.php VERSION actions/WidgetView.php assets/css/device-health.css assets/js/class.widget.js collector/ZabbixDeviceHealthCollector.php config/Limits.php config/HealthConfigRepository.php config/FirstObservedRepository.php config/device-health.json domain/MetricFreshnessPolicy.php domain/ItemClassifier.php domain/IssueNormalizer.php domain/DeviceHealthResolver.php views/widget.view.php RELEASE.sha256;do [[ -r $m/$f ]]||dh_fail "missing $f";done
	v=$(tr -d '[:space:]'<"$m/VERSION");mv=$($DH_PHP -r '$d=json_decode(file_get_contents($argv[1]),true);echo $d["version"]??"";' "$m/manifest.json");[[ $v == "$mv" ]]||dh_fail 'manifest/VERSION mismatch';(cd "$m"&&sha256sum --quiet -c RELEASE.sha256)||dh_fail 'checksum failure';
	while IFS= read -r -d '' f;do "$DH_PHP" -l "$f">/dev/null||dh_fail "PHP lint: $f";done < <(find "$m" -name '*.php' -type f -print0);dh_config "$m" "$m/config/device-health.json";DH_VERSION=$v;
}
dh_identity(){ local p=${DEVICE_HEALTH_PHP_FPM_POOL:-/etc/php-fpm.d/www.conf};DH_USER=${DEVICE_HEALTH_RUNTIME_USER:-$(sed -nE 's/^[[:space:]]*user[[:space:]]*=[[:space:]]*([^[:space:];]+).*/\1/p' "$p"|head -n1)};DH_GROUP=${DEVICE_HEALTH_RUNTIME_GROUP:-$(sed -nE 's/^[[:space:]]*group[[:space:]]*=[[:space:]]*([^[:space:];]+).*/\1/p' "$p"|head -n1)};getent passwd "$DH_USER">/dev/null&&getent group "$DH_GROUP">/dev/null||dh_fail 'PHP-FPM identity unavailable'; }

#!/usr/bin/env bash
dr_fail(){ printf 'FAIL: %s\n' "$*" >&2; exit 1; }
dr_warn(){ printf 'WARNING: %s\n' "$*"; }
dr_info(){ printf '%s\n' "$*"; }
dr_need(){ command -v "$1" >/dev/null 2>&1 || dr_fail "required command not found: $1"; }
dr_root(){ [[ ${EUID:-$(id -u)} -eq 0 ]] || dr_fail 'run as root (for example, with sudo)'; }
dr_prefix(){ local root=${DAILY_REPORTING_ROOT:-}; printf '%s%s' "${root%/}" "$1"; }
dr_os(){
  local file=${DAILY_REPORTING_OS_RELEASE:-/etc/os-release} ID='' VERSION_ID='' PRETTY_NAME=''
  [[ -r $file ]] || dr_fail "cannot read OS release: $file"
  # shellcheck disable=SC1090
  source "$file"
  [[ $ID == rhel && ${VERSION_ID%%.*} == 9 ]] || dr_fail "RHEL 9 required; found ${PRETTY_NAME:-$ID}"
  DR_OS=${PRETTY_NAME:-RHEL 9}
}
dr_python(){
  DR_PYTHON=${PYTHON_BIN:-python3}; dr_need "$DR_PYTHON"
  "$DR_PYTHON" -c 'import sys;raise SystemExit(0 if sys.version_info >= (3,9) else 1)' || dr_fail 'Python 3.9 or newer required'
}
dr_validate_config(){ PYTHONPATH="$1/bin" "$DR_PYTHON" -c 'import sys;from zabbix_daily_report import load_config;load_config(sys.argv[1])' "$2"; }
dr_manifest(){
  local root=$1
  [[ -r $root/MANIFEST.sha256 ]] || dr_fail 'MANIFEST.sha256 missing'
  (cd "$root" && sha256sum --quiet -c MANIFEST.sha256) || dr_fail 'bundle checksum validation failed'
}
dr_has_credentials(){
  local file=$1
  [[ -r $file ]] || return 1
  grep -Eq '^ZABBIX_API_TOKEN=.+$' "$file" || { grep -Eq '^ZABBIX_API_USER=.+$' "$file" && grep -Eq '^ZABBIX_API_PASSWORD=.+$' "$file"; }
}
dr_schedule_calendar(){
  local app=$1 config=$2
  PYTHONPATH="$app/bin" "$DR_PYTHON" -c 'import sys;from zabbix_daily_report import load_config;c=load_config(sys.argv[1]);print("*-*-* "+c["report"]["schedule_local"]+":00")' "$config"
}
dr_capture_native_state(){
  local destination=$1 dropin=$2
  [[ -e $destination/state ]] && return 0
  install -d -m 0750 "$destination"
  if [[ -f $dropin ]]; then cp -a "$dropin" "$destination/daily-reporting.conf"; printf 'PRESENT\n' >"$destination/state"; else printf 'ABSENT\n' >"$destination/state"; fi
}
dr_restore_native_state(){
  local source=$1 dropin=$2 state
  [[ -r $source/state ]] || dr_fail "native baseline state missing: $source/state"
  state=$(tr -d '[:space:]' <"$source/state")
  case "$state" in
    PRESENT) [[ -f $source/daily-reporting.conf ]] || dr_fail 'native baseline copy missing'; install -d -m 0755 "$(dirname "$dropin")"; cp -a "$source/daily-reporting.conf" "$dropin"; DR_NATIVE_RESTORE_ACTION=RESTORED ;;
    ABSENT) rm -f -- "$dropin"; DR_NATIVE_RESTORE_ACTION=REMOVED ;;
    *) dr_fail "invalid native baseline state: $state" ;;
  esac
}

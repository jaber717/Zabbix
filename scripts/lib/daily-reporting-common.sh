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

# ---------------------------------------------------------------- reporting suite (PDF/XLSX/JSON)
dr_validate_suite(){ PYTHONPATH="$1/lib" "$DR_PYTHON" -c 'import sys;from zrs.config import load_suite;load_suite(sys.argv[1])' "$2"; }
dr_suite_calendar(){ PYTHONPATH="$1/lib" "$DR_PYTHON" -c 'import sys;from zrs.config import load_suite,on_calendar;print(on_calendar(load_suite(sys.argv[1]),sys.argv[2]))' "$2" "$3"; }
dr_suite_delivery_state(){
  PYTHONPATH="$1/lib" "$DR_PYTHON" -c 'import sys;from zrs.config import load_suite;d=load_suite(sys.argv[1])["delivery"];print("DISABLED" if not d["enabled"] else ("ENABLED_TEST_RECIPIENTS_ONLY" if d["mode"]=="test" else "ENABLED_LIVE_REQUIRES_ZRS_ALLOW_LIVE_DELIVERY"))' "$2"
}
# Verify every pinned wheel against wheels.lock (SHA-256), then extract into <dest>. No pip, no network.
dr_wheel_extract(){
  local wheelhouse=$1 lock=$2 dest=$3
  "$DR_PYTHON" - "$wheelhouse" "$lock" "$dest" <<'PY'
import hashlib, os, sys, zipfile
wheelhouse, lock, dest = sys.argv[1:4]
paths = []
for line in open(lock):
    line = line.strip()
    if not line or line.startswith('#'):
        continue
    sha, name = line.split(None, 2)[:2]
    path = os.path.join(wheelhouse, name)
    if not os.path.isfile(path):
        sys.exit('MISSING WHEEL: ' + name)
    if hashlib.sha256(open(path, 'rb').read()).hexdigest() != sha:
        sys.exit('HASH MISMATCH: ' + name)
    paths.append(path)
if not paths:
    sys.exit('wheels.lock lists no wheels')
if dest:
    root = os.path.abspath(dest)
    os.makedirs(root, exist_ok=True)
    for path in paths:
        with zipfile.ZipFile(path) as z:
            for member in z.namelist():
                target = os.path.abspath(os.path.join(root, member))
                if target != root and not target.startswith(root + os.sep):
                    sys.exit('UNSAFE PATH in ' + os.path.basename(path))
            z.extractall(root)
print(len(paths))
PY
}
# Offline dependency installation into <stage>/vendor (called before the application directory is swapped in).
dr_suite_deps(){
  local source=$1 stage=$2 previous=$3 wheelhouse lock n
  wheelhouse=${DAILY_REPORTING_WHEELHOUSE:-$source/wheelhouse}; lock=${DAILY_REPORTING_WHEEL_LOCK:-$source/wheels.lock}
  if [[ -d $wheelhouse ]] && compgen -G "$wheelhouse/*.whl" >/dev/null; then
    [[ -r $lock ]] || dr_fail 'wheels.lock is missing; refusing to install unpinned dependencies'
    n=$(dr_wheel_extract "$wheelhouse" "$lock" "$stage/vendor") || dr_fail 'dependency wheel verification/extraction failed (see message above)'
    find "$stage/vendor" -type d -exec chmod 0755 {} +; find "$stage/vendor" -type f -exec chmod 0644 {} +
    # the strongest import check there is: render all three formats from the bundled synthetic dataset with the staged copy
    "$DR_PYTHON" "$stage/bin/zabbix_report_suite.py" --selftest >/dev/null 2>&1 || dr_fail 'SUITE_DEPENDENCIES=FAIL: wheels verified but the PDF/XLSX self-test fails on this Python (wrong ABI or missing library); nothing was installed'
    dr_info "SUITE_DEPENDENCIES=PASS wheels=$n"
  elif [[ -d $previous/vendor ]]; then
    cp -a "$previous/vendor" "$stage/vendor"; dr_info 'SUITE_DEPENDENCIES=PRESERVED'
  else
    dr_warn 'SUITE_DEPENDENCIES=NOT_INSTALLED (no wheelhouse in this bundle): PDF/XLSX reports are unavailable; the RC2 HTML/JSON report is unaffected'
  fi
  rm -rf -- "$stage/wheelhouse"
}
# Suite configuration, service and (disabled) timers. Never enables anything unless asked.
dr_install_suite(){
  local source=$1 app=$2 etc=$3 systemd=$4 backup=$5 enable=$6 kind cal staged
  if [[ ! -f $etc/suite.json ]]; then install -m 0640 "$source/config/suite.example.json" "$etc/suite.json"; else cp -a "$etc/suite.json" "$backup/suite.json"; dr_info 'SUITE_CONFIG=PRESERVED'; fi
  dr_validate_suite "$app" "$etc/suite.json" || dr_fail 'installed suite.json is invalid; suite timers were not installed'
  install -m 0644 "$source/systemd/zabbix-report-suite@.service" "$systemd/zabbix-report-suite@.service"
  for kind in daily weekly monthly; do
    cal=$(dr_suite_calendar "$app" "$etc/suite.json" "$kind"); staged="$backup/zabbix-report-suite-$kind.timer"
    sed "s|__ZRS_ON_CALENDAR__|$cal|" "$source/systemd/zabbix-report-suite-$kind.timer" >"$staged"
    grep -Fxq "OnCalendar=$cal" "$staged" || dr_fail "suite $kind timer rendering failed"
    install -m 0644 "$staged" "$systemd/zabbix-report-suite-$kind.timer"; dr_info "SUITE_TIMER_${kind^^}=$cal"
  done
  dr_info "SUITE_DELIVERY=$(dr_suite_delivery_state "$app" "$etc/suite.json")"
  if [[ -z ${DAILY_REPORTING_ROOT:-} ]]; then
    chown root:zabbix-report "$etc/suite.json"; chmod 0640 "$etc/suite.json"
    local was_active=0; systemctl is-active --quiet zabbix-report-suite-daily.timer && was_active=1 || true
    systemctl daemon-reload
    if ((enable)); then
      dr_has_credentials "$etc/secrets.env" || dr_fail 'refusing to enable suite timers: API credentials are absent'
      for kind in daily weekly monthly; do systemctl enable --now "zabbix-report-suite-$kind.timer"; done; dr_info 'SUITE_TIMERS=ENABLED'
    elif ((was_active)); then for kind in daily weekly monthly; do systemctl restart "zabbix-report-suite-$kind.timer"; done; dr_info 'SUITE_TIMERS=ENABLED (unchanged)'
    else dr_info 'SUITE_TIMERS=INSTALLED_DISABLED'; fi
  else dr_info 'SUITE_TIMERS=INSTALLED_DISABLED'; fi
}

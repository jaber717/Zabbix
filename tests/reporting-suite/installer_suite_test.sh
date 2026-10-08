#!/usr/bin/env bash
# Isolated-root test of the installer/verifier/rollback for the reporting suite: offline dependency installation,
# idempotency, tamper detection, schedule rendering, and upgrade from / rollback to RC2.
#
#   WHEELHOUSE=<dir with the wheels matching THIS python> bash tests/reporting-suite/installer_suite_test.sh
#   RC2_TREE=<dir from: git archive daily-reporting-v1.0.0-rc2 | tar -x -C DIR>   (enables the upgrade/rollback section)
#
# WHEELHOUSE defaults to reporting/daily-reporting/wheelhouse (the real RHEL 9 / Python 3.9 wheels). On any other Python
# the ABI-specific wheel (Pillow) must be replaced by a matching one, as the installer's import check will refuse otherwise.
set -Eeuo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P); TMP=$(mktemp -d); trap 'rm -rf -- "$TMP"' EXIT
WHEELHOUSE=${WHEELHOUSE:-$ROOT/reporting/daily-reporting/wheelhouse}
pass(){ printf '%s=PASS\n' "$1"; }
fail(){ printf 'FAIL: %s\n' "$*" >&2; exit 1; }
printf 'ID=rhel\nVERSION_ID=9.6\nPRETTY_NAME="Red Hat Enterprise Linux 9.6"\n' >"$TMP/os-release"
make_lock(){ # wheelhouse -> lock file with real hashes
  local wh=$1 out=$2; : >"$out"
  for w in "$wh"/*.whl; do printf '%s  %s  https://example.invalid/%s\n' "$(sha256sum "$w" | awk '{print $1}')" "$(basename "$w")" "$(basename "$w")" >>"$out"; done
}
make_lock "$WHEELHOUSE" "$TMP/wheels.lock"
export DAILY_REPORTING_ROOT="$TMP/root" DAILY_REPORTING_OS_RELEASE="$TMP/os-release" DAILY_REPORTING_WHEELHOUSE="$WHEELHOUSE" DAILY_REPORTING_WHEEL_LOCK="$TMP/wheels.lock"
R="$TMP/root"; APP="$R/opt/zabbix-daily-reporting"; ETC="$R/etc/zabbix-daily-reporting"; SD="$R/etc/systemd/system"

# ---- 1. fresh install: offline dependencies, suite config, disabled timers
out=$(bash "$ROOT/scripts/install_daily_reporting.sh")
grep -Fq 'RELEASE_SUITE_CONFIG=PASS' <<<"$out" || fail 'release suite config not validated'
grep -Fq 'SUITE_WHEELHOUSE=PASS' <<<"$out" || fail 'wheelhouse not verified in preflight section'
grep -Eq 'SUITE_DEPENDENCIES=PASS wheels=[0-9]+' <<<"$out" || fail "dependencies not installed: $out"
grep -Fq 'SUITE_TIMERS=INSTALLED_DISABLED' <<<"$out" || fail 'suite timers must be installed disabled'
grep -Fq 'SUITE_DELIVERY=DISABLED' <<<"$out" || fail 'delivery must default to disabled'
grep -Fq 'SUITE_TIMER_DAILY=*-*-* 06:30:00' <<<"$out"; grep -Fq 'SUITE_TIMER_WEEKLY=Mon *-*-* 06:45:00' <<<"$out"; grep -Fq 'SUITE_TIMER_MONTHLY=*-*-01 07:00:00' <<<"$out"
test -d "$APP/vendor/reportlab"; test -d "$APP/vendor/openpyxl"; test ! -e "$APP/wheelhouse"
test "$(stat -c %a "$ETC/suite.json")" = 640
grep -Fxq 'OnCalendar=Mon *-*-* 06:45:00' "$SD/zabbix-report-suite-weekly.timer"
grep -Fq 'Unit=zabbix-report-suite@weekly.service' "$SD/zabbix-report-suite-weekly.timer"
grep -Fq -- '--cadence %i --send' "$SD/zabbix-report-suite@.service"
test ! -e "$R/etc/systemd/system/timers.target.wants"                    # nothing enabled
pass FRESH_INSTALL_OFFLINE_DEPENDENCIES

# ---- 2. verifier incl. self-test on the INSTALLED copy
v=$(bash "$ROOT/scripts/verify_daily_reporting.sh")
grep -Fq 'SUITE_CONFIGURATION=PASS' <<<"$v"; grep -Fq 'SUITE_SELFTEST=PASS' <<<"$v"; grep -Fq 'RESULT=PASS' <<<"$v"
pass VERIFY_WITH_SELFTEST

# ---- 3. the installed command works without Zabbix: plan + selftest
plan=$(PYTHONPATH="$APP/vendor" python3 "$APP/bin/zabbix_report_suite.py" --config "$ETC/report.json" --suite-config "$ETC/suite.json" --plan --now 2026-10-08T07:00:00+03:00)
grep -Fq 'PLAN report=daily_network_health kind=daily period=2026-10-07' <<<"$plan"; grep -Fq 'period=2026-09' <<<"$plan"
pass INSTALLED_PLAN

# ---- 4. idempotent re-install preserves operator configuration
cp "$ETC/suite.json" "$TMP/suite.before"; sha_cfg=$(sha256sum "$ETC/report.json" | awk '{print $1}')
sed -i 's/"weekly": "Mon 06:45"/"weekly": "Tue 05:10"/' "$ETC/suite.json"; cp "$ETC/suite.json" "$TMP/suite.edited"
out2=$(bash "$ROOT/scripts/install_daily_reporting.sh")
grep -Fq 'SUITE_CONFIG=PRESERVED' <<<"$out2"; cmp -s "$TMP/suite.edited" "$ETC/suite.json"
test "$sha_cfg" = "$(sha256sum "$ETC/report.json" | awk '{print $1}')"
grep -Fxq 'OnCalendar=Tue *-*-* 05:10:00' "$SD/zabbix-report-suite-weekly.timer"
pass IDEMPOTENT_REINSTALL_PRESERVES_CONFIG
# without a wheelhouse the installed vendor directory is kept
out3=$(DAILY_REPORTING_WHEELHOUSE="$TMP/none" bash "$ROOT/scripts/install_daily_reporting.sh")
grep -Fq 'SUITE_DEPENDENCIES=PRESERVED' <<<"$out3"; test -d "$APP/vendor/reportlab"
pass VENDOR_PRESERVED_WITHOUT_WHEELHOUSE

# ---- 5. tamper detection: a modified wheel is refused and the installed application is left untouched
app_before=$(cd "$APP" && find . -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum)
mkdir "$TMP/evil"; cp "$WHEELHOUSE"/*.whl "$TMP/evil/"; first=$(ls "$TMP/evil"/*.whl | head -n1); printf 'x' >>"$first"
set +e; bad=$(DAILY_REPORTING_WHEELHOUSE="$TMP/evil" bash "$ROOT/scripts/install_daily_reporting.sh" 2>&1); bad_rc=$?; set -e
test "$bad_rc" -ne 0; grep -Fq 'HASH MISMATCH' <<<"$bad"
test "$app_before" = "$(cd "$APP" && find . -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum)" || fail 'application changed despite refused install'
pass TAMPERED_WHEEL_REFUSED
set +e; DAILY_REPORTING_WHEEL_LOCK="$TMP/missing.lock" bash "$ROOT/scripts/install_daily_reporting.sh" >/dev/null 2>&1; lock_rc=$?; set -e
test "$lock_rc" -ne 0; pass MISSING_LOCK_REFUSED

# ---- 6. invalid suite configuration stops the install before timers are touched; verifier detects a timer mismatch
cp "$ETC/suite.json" "$TMP/suite.good"
sed -i 's/"daily": "06:30"/"daily": "29:99"/' "$ETC/suite.json"
set +e; bad2=$(bash "$ROOT/scripts/install_daily_reporting.sh" 2>&1); rc2=$?; set -e
test "$rc2" -ne 0; cp "$TMP/suite.good" "$ETC/suite.json"
sed -i 's/Tue \*-\*-\* 05:10:00/Wed *-*-* 05:10:00/' "$SD/zabbix-report-suite-weekly.timer"
set +e; mm=$(bash "$ROOT/scripts/verify_daily_reporting.sh" 2>&1); mm_rc=$?; set -e
test "$mm_rc" -ne 0; grep -Fq 'suite weekly timer schedule mismatch' <<<"$mm"
bash "$ROOT/scripts/install_daily_reporting.sh" >/dev/null
pass INVALID_CONFIG_AND_TIMER_MISMATCH_DETECTED

# ---- 7. rollback removes the suite units, keeps configuration and generated reports
mkdir -p "$R/var/lib/zabbix-daily-reporting/suite/daily-network-health/2026-10-07"; printf 'report' >"$R/var/lib/zabbix-daily-reporting/suite/daily-network-health/2026-10-07/keep.pdf"
rb=$(bash "$ROOT/scripts/rollback_daily_reporting.sh" --confirm); grep -Fq 'SUITE_UNITS=REMOVED' <<<"$rb"
test ! -e "$SD/zabbix-report-suite@.service"; test ! -e "$SD/zabbix-report-suite-daily.timer"
test -f "$ETC/suite.json"; test -f "$ETC/report.json"; test -f "$R/var/lib/zabbix-daily-reporting/suite/daily-network-health/2026-10-07/keep.pdf"
pass ROLLBACK_PRESERVES_CONFIG_AND_REPORTS

# ---- 8. upgrade from RC2 (needs RC2_TREE) and rollback back to it
if [[ -n ${RC2_TREE:-} && -d $RC2_TREE/scripts ]]; then
  rm -rf "$R"; export DAILY_REPORTING_ROOT="$TMP/root2"; R="$TMP/root2"; APP="$R/opt/zabbix-daily-reporting"; ETC="$R/etc/zabbix-daily-reporting"; SD="$R/etc/systemd/system"
  unset DAILY_REPORTING_WHEELHOUSE DAILY_REPORTING_WHEEL_LOCK
  bash "$RC2_TREE/scripts/install_daily_reporting.sh" >/dev/null
  grep -Fxq '1.0.0-rc2' "$APP/VERSION" || fail 'RC2 baseline not installed'
  printf 'ZABBIX_API_TOKEN=rc2-secret-value\n' >>"$ETC/secrets.env"
  sed -i 's/"schedule_local": "07:00"/"schedule_local": "06:10"/' "$ETC/report.json"
  bash "$RC2_TREE/scripts/install_daily_reporting.sh" >/dev/null     # RC2 re-render of the timer
  cfg=$(sha256sum "$ETC/report.json" | awk '{print $1}'); sec=$(sha256sum "$ETC/secrets.env" | awk '{print $1}'); tim=$(sha256sum "$SD/zabbix-daily-report.timer" | awk '{print $1}')
  mkdir -p "$R/var/lib/zabbix-daily-reporting/reports"; printf '<html>rc2</html>' >"$R/var/lib/zabbix-daily-reporting/reports/daily-network-health-2026-10-06.html"
  export DAILY_REPORTING_WHEELHOUSE="$WHEELHOUSE" DAILY_REPORTING_WHEEL_LOCK="$TMP/wheels.lock"
  up=$(bash "$ROOT/scripts/install_daily_reporting.sh")
  grep -Fq 'INSTALLED_CONFIG=PASS' <<<"$up"; grep -Fq 'CONFIG=PRESERVED' <<<"$up"; grep -Fq 'SECRETS=PRESERVED' <<<"$up"
  grep -Fq 'SUITE_CONFIG' <<<"$up"; grep -Fxq '1.1.0-rc1' "$APP/VERSION"
  test "$cfg" = "$(sha256sum "$ETC/report.json" | awk '{print $1}')"; test "$sec" = "$(sha256sum "$ETC/secrets.env" | awk '{print $1}')"
  test "$tim" = "$(sha256sum "$SD/zabbix-daily-report.timer" | awk '{print $1}')"                  # RC2 timer unchanged
  test -f "$R/var/lib/zabbix-daily-reporting/reports/daily-network-health-2026-10-06.html"
  vv=$(bash "$ROOT/scripts/verify_daily_reporting.sh"); grep -Fq 'RESULT=PASS' <<<"$vv"
  # the unchanged RC2 collector still loads the (unchanged) RC2 configuration from the upgraded application
  PYTHONPATH="$APP/bin" python3 -c 'import sys;from zabbix_daily_report import load_config;load_config(sys.argv[1])' "$ETC/report.json"
  pass UPGRADE_FROM_RC2_COMPATIBLE
  rb2=$(bash "$ROOT/scripts/rollback_daily_reporting.sh" --confirm); grep -Fq 'APPLICATION=RESTORED' <<<"$rb2"
  grep -Fxq '1.0.0-rc2' "$APP/VERSION"; test ! -e "$APP/lib"; test ! -e "$SD/zabbix-report-suite@.service"
  test "$cfg" = "$(sha256sum "$ETC/report.json" | awk '{print $1}')"; test "$sec" = "$(sha256sum "$ETC/secrets.env" | awk '{print $1}')"
  pass ROLLBACK_TO_RC2
else
  printf 'UPGRADE_FROM_RC2=SKIPPED (set RC2_TREE)\n'
fi
printf 'RESULT=PASS\n'

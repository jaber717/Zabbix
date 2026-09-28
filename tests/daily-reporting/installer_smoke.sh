#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P); TMP=$(mktemp -d); trap 'rm -rf -- "$TMP"' EXIT
printf 'ID=rhel\nVERSION_ID=9.6\nPRETTY_NAME="Red Hat Enterprise Linux 9.6"\n' >"$TMP/os-release"
export DAILY_REPORTING_ROOT="$TMP/root" DAILY_REPORTING_OS_RELEASE="$TMP/os-release"
bash "$ROOT/scripts/install_daily_reporting.sh"
test -f "$TMP/root/etc/zabbix-daily-reporting/report.json"
test "$(stat -c %a "$TMP/root/etc/zabbix-daily-reporting/secrets.env")" = 600
sed -i 's/"schedule_local": "07:00"/"schedule_local": "06:35"/' "$TMP/root/etc/zabbix-daily-reporting/report.json"
printf 'ZABBIX_API_TOKEN=test-value\n' >>"$TMP/root/etc/zabbix-daily-reporting/secrets.env"
config_before=$(sha256sum "$TMP/root/etc/zabbix-daily-reporting/report.json" | awk '{print $1}')
secrets_before=$(sha256sum "$TMP/root/etc/zabbix-daily-reporting/secrets.env" | awk '{print $1}')
second_output=$(bash "$ROOT/scripts/install_daily_reporting.sh")
grep -Fq 'INSTALLED_CONFIG=PASS' <<<"$second_output"
grep -Fq 'CONFIG=PRESERVED' <<<"$second_output"
grep -Fq 'SECRETS=PRESERVED' <<<"$second_output"
test "$config_before" = "$(sha256sum "$TMP/root/etc/zabbix-daily-reporting/report.json" | awk '{print $1}')"
test "$secrets_before" = "$(sha256sum "$TMP/root/etc/zabbix-daily-reporting/secrets.env" | awk '{print $1}')"
grep -Fxq 'OnCalendar=*-*-* 06:35:00' "$TMP/root/etc/systemd/system/zabbix-daily-report.timer"
verify_output=$(bash "$ROOT/scripts/verify_daily_reporting.sh")
grep -Fq 'TIMER_SCHEDULE=*-*-* 06:35:00' <<<"$verify_output"
preflight_output=$(bash "$ROOT/scripts/install_daily_reporting.sh" --preflight)
grep -Fq 'RELEASE_CONFIG=PASS' <<<"$preflight_output"
grep -Fq 'INSTALLED_CONFIG=PASS' <<<"$preflight_output"
cp "$TMP/root/etc/zabbix-daily-reporting/report.json" "$TMP/valid-report.json"
sed -i 's/"schedule_local": "06:35"/"schedule_local": "29:00"/' "$TMP/root/etc/zabbix-daily-reporting/report.json"
set +e; invalid_output=$(bash "$ROOT/scripts/install_daily_reporting.sh" --preflight 2>&1); invalid_rc=$?; set -e
test "$invalid_rc" -eq 2; grep -Fq 'RELEASE_CONFIG=PASS' <<<"$invalid_output"; grep -Fq 'INSTALLED_CONFIG=WARNING' <<<"$invalid_output"
cp "$TMP/valid-report.json" "$TMP/root/etc/zabbix-daily-reporting/report.json"
cp "$TMP/root/etc/systemd/system/zabbix-daily-report.timer" "$TMP/valid-timer"
sed -i 's/06:35:00/05:00:00/' "$TMP/root/etc/systemd/system/zabbix-daily-report.timer"
set +e; mismatch_output=$(bash "$ROOT/scripts/verify_daily_reporting.sh" 2>&1); mismatch_rc=$?; set -e
test "$mismatch_rc" -ne 0; grep -Fq 'timer schedule mismatch' <<<"$mismatch_output"
cp "$TMP/valid-timer" "$TMP/root/etc/systemd/system/zabbix-daily-report.timer"
bash "$ROOT/scripts/rollback_daily_reporting.sh" --confirm
test -f "$TMP/root/etc/zabbix-daily-reporting/report.json"
test -d "$TMP/root/var/lib/zabbix-daily-reporting/reports"
printf 'IDEMPOTENT_DOUBLE_INSTALL=PASS\nRESULT=PASS\n'

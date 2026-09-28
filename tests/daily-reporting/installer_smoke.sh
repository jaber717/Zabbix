#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P); TMP=$(mktemp -d); trap 'rm -rf -- "$TMP"' EXIT
printf 'ID=rhel\nVERSION_ID=9.6\nPRETTY_NAME="Red Hat Enterprise Linux 9.6"\n' >"$TMP/os-release"
export DAILY_REPORTING_ROOT="$TMP/root" DAILY_REPORTING_OS_RELEASE="$TMP/os-release"
bash "$ROOT/scripts/install_daily_reporting.sh"
bash "$ROOT/scripts/verify_daily_reporting.sh"
test -f "$TMP/root/etc/zabbix-daily-reporting/report.json"
test "$(stat -c %a "$TMP/root/etc/zabbix-daily-reporting/secrets.env")" = 600
bash "$ROOT/scripts/rollback_daily_reporting.sh" --confirm
test -f "$TMP/root/etc/zabbix-daily-reporting/report.json"
test -d "$TMP/root/var/lib/zabbix-daily-reporting/reports"
printf 'RESULT=PASS\n'

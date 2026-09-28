#!/usr/bin/env bash
set -Eeuo pipefail
DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck source=scripts/lib/daily-reporting-common.sh
source "$DIR/lib/daily-reporting-common.sh"
[[ $# -eq 0 ]] || dr_fail 'usage: verify_daily_reporting.sh'
dr_os; dr_python
APP=$(dr_prefix /opt/zabbix-daily-reporting); ETC=$(dr_prefix /etc/zabbix-daily-reporting); STATE=$(dr_prefix /var/lib/zabbix-daily-reporting); SYSTEMD=$(dr_prefix /etc/systemd/system)
for file in "$APP/VERSION" "$APP/bin/zabbix_daily_report.py" "$APP/bin/native_preflight.py" "$APP/bin/native_reporting.py" "$ETC/report.json" "$ETC/secrets.env" "$SYSTEMD/zabbix-daily-report.service" "$SYSTEMD/zabbix-daily-report.timer"; do [[ -r $file ]] || dr_fail "missing $file"; done
"$DR_PYTHON" -m py_compile "$APP/bin/"*.py
dr_validate_config "$APP" "$ETC/report.json"
EXPECTED_CALENDAR=$(dr_schedule_calendar "$APP" "$ETC/report.json")
grep -Fxq "OnCalendar=$EXPECTED_CALENDAR" "$SYSTEMD/zabbix-daily-report.timer" || dr_fail "timer schedule mismatch; expected $EXPECTED_CALENDAR"
[[ $(stat -c %a "$ETC/secrets.env") == 600 ]] || dr_fail 'secrets.env must be mode 0600'
[[ -d $STATE/reports ]] || dr_fail 'report output directory missing'
set +e; "$DR_PYTHON" "$APP/bin/native_preflight.py"; native_rc=$?; set -e
((native_rc==0)) && dr_info 'NATIVE_PDF=PASS' || dr_warn 'NATIVE_PDF=NOT_READY (custom report validation passed)'
dr_has_credentials "$ETC/secrets.env" && dr_info 'API_CREDENTIALS=CONFIGURED' || dr_warn 'API_CREDENTIALS=NOT_CONFIGURED'
if [[ -z ${DAILY_REPORTING_ROOT:-} ]] && systemctl is-active --quiet zabbix-daily-report.timer; then systemctl cat zabbix-daily-report.timer | grep -Fxq "OnCalendar=$EXPECTED_CALENDAR" || dr_fail 'active timer does not match report.schedule_local'; dr_info 'ACTIVE_TIMER_SCHEDULE=PASS'; else dr_info 'ACTIVE_TIMER_SCHEDULE=NOT_ACTIVE'; fi
dr_info "TIMER_SCHEDULE=$EXPECTED_CALENDAR"; dr_info 'PYTHON_SYNTAX=PASS'; dr_info 'CONFIGURATION=PASS'; dr_info 'RESULT=PASS'

#!/usr/bin/env bash
set -Eeuo pipefail
DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck source=scripts/lib/daily-reporting-common.sh
source "$DIR/lib/daily-reporting-common.sh"
[[ $# -eq 1 && $1 == --confirm ]] || dr_fail 'usage: rollback_daily_reporting.sh --confirm'
dr_root; APP=$(dr_prefix /opt/zabbix-daily-reporting); SYSTEMD=$(dr_prefix /etc/systemd/system); BACKUPS=$(dr_prefix /var/backups/zabbix-daily-reporting); STAMP=$(date -u +%Y%m%d-%H%M%S-%N)
if [[ -z ${DAILY_REPORTING_ROOT:-} ]]; then systemctl disable --now zabbix-daily-report.timer zabbix-report-suite-daily.timer zabbix-report-suite-weekly.timer zabbix-report-suite-monthly.timer 2>/dev/null || true; fi
LATEST=$(find "$BACKUPS" -mindepth 1 -maxdepth 1 -type d ! -name 'native-baseline*' -printf '%f\n' 2>/dev/null | sort | tail -n1 || true)
[[ -d $APP ]] && mv "$APP" "${APP}.removed-$STAMP"
if [[ -n $LATEST && -d $BACKUPS/$LATEST/application ]]; then cp -a "$BACKUPS/$LATEST/application" "$APP"; dr_info "APPLICATION=RESTORED:$LATEST"; else dr_warn 'no prior application backup was available'; fi
rm -f "$SYSTEMD/zabbix-daily-report.service" "$SYSTEMD/zabbix-daily-report.timer" "$SYSTEMD/zabbix-report-suite@.service" "$SYSTEMD"/zabbix-report-suite-{daily,weekly,monthly}.timer
BASELINE="$BACKUPS/native-baseline"; DROPIN=$(dr_prefix /etc/zabbix/zabbix_server.conf.d/daily-reporting.conf); SERVER=$(dr_prefix /etc/zabbix/zabbix_server.conf)
if [[ -r $BASELINE/state ]]; then
  dr_restore_native_state "$BASELINE" "$DROPIN"; dr_info "NATIVE_CONFIGURATION=$DR_NATIVE_RESTORE_ACTION:$DROPIN"
  ZABBIX_SERVER_BIN=${DAILY_REPORTING_ZABBIX_SERVER_BIN:-zabbix_server}; "$ZABBIX_SERVER_BIN" -T -c "$SERVER" >/dev/null || dr_fail 'restored Zabbix server configuration failed validation; service was not restarted'
  SYSTEMCTL=${DAILY_REPORTING_SYSTEMCTL:-systemctl}; "$SYSTEMCTL" restart "${DAILY_REPORTING_ZABBIX_SERVICE:-zabbix-server}"
  mv "$BASELINE" "$BACKUPS/native-baseline.restored-$STAMP"
  dr_info 'NATIVE_CONFIGURATION_VALIDATION=PASS'; dr_info "ZABBIX_SERVER_SERVICE_RESTARTED=${DAILY_REPORTING_ZABBIX_SERVICE:-zabbix-server}"
else dr_info 'NATIVE_CONFIGURATION=UNCHANGED:NO_PROJECT_BASELINE'; fi
if [[ -z ${DAILY_REPORTING_ROOT:-} ]]; then systemctl daemon-reload; fi
dr_info "SUITE_UNITS=REMOVED"; dr_info "CONFIGURATION=PRESERVED:$(dr_prefix /etc/zabbix-daily-reporting)"; dr_info "REPORTS=PRESERVED:$(dr_prefix /var/lib/zabbix-daily-reporting)"; dr_info 'RESULT=PASS'

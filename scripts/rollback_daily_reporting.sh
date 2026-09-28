#!/usr/bin/env bash
set -Eeuo pipefail
DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck source=scripts/lib/daily-reporting-common.sh
source "$DIR/lib/daily-reporting-common.sh"
[[ $# -eq 1 && $1 == --confirm ]] || dr_fail 'usage: rollback_daily_reporting.sh --confirm'
dr_root; APP=$(dr_prefix /opt/zabbix-daily-reporting); SYSTEMD=$(dr_prefix /etc/systemd/system); BACKUPS=$(dr_prefix /var/backups/zabbix-daily-reporting); STAMP=$(date -u +%Y%m%d-%H%M%S)
if [[ -z ${DAILY_REPORTING_ROOT:-} ]]; then systemctl disable --now zabbix-daily-report.timer 2>/dev/null || true; fi
LATEST=$(find "$BACKUPS" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2>/dev/null | sort | tail -n1 || true)
[[ -d $APP ]] && mv "$APP" "${APP}.removed-$STAMP"
if [[ -n $LATEST && -d $BACKUPS/$LATEST/application ]]; then cp -a "$BACKUPS/$LATEST/application" "$APP"; dr_info "APPLICATION=RESTORED:$LATEST"; else dr_warn 'no prior application backup was available'; fi
rm -f "$SYSTEMD/zabbix-daily-report.service" "$SYSTEMD/zabbix-daily-report.timer"
if [[ -n $LATEST && -f $BACKUPS/$LATEST/daily-reporting.conf ]]; then install -m 0644 "$BACKUPS/$LATEST/daily-reporting.conf" "$(dr_prefix /etc/zabbix/zabbix_server.conf.d/daily-reporting.conf)"; fi
if [[ -z ${DAILY_REPORTING_ROOT:-} ]]; then systemctl daemon-reload; fi
dr_info "CONFIGURATION=PRESERVED:$(dr_prefix /etc/zabbix-daily-reporting)"; dr_info "REPORTS=PRESERVED:$(dr_prefix /var/lib/zabbix-daily-reporting)"; dr_info 'RESULT=PASS'

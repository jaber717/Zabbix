#!/usr/bin/env bash
set -Eeuo pipefail
DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P); ROOT=$(cd "$DIR/.." && pwd -P)
# shellcheck source=scripts/lib/daily-reporting-common.sh
source "$DIR/lib/daily-reporting-common.sh"
PREFLIGHT=0; ENABLE_TIMER=0; APPLY_NATIVE=0
while (($#)); do case "$1" in --preflight) PREFLIGHT=1;; --enable-timer) ENABLE_TIMER=1;; --apply-native-config) APPLY_NATIVE=1;; *) dr_fail 'usage: install_daily_reporting.sh [--preflight] [--enable-timer] [--apply-native-config]' ;; esac; shift; done
dr_need sha256sum; dr_need install; dr_os; dr_python
SOURCE="$ROOT/reporting/daily-reporting"; [[ -d $SOURCE ]] || dr_fail "project files missing: $SOURCE"
[[ -r $ROOT/MANIFEST.sha256 ]] && dr_manifest "$ROOT"
CONFIG_SOURCE="$SOURCE/config/report.example.json"; dr_validate_config "$SOURCE" "$CONFIG_SOURCE"; dr_info 'RELEASE_CONFIG=PASS'
APP=$(dr_prefix /opt/zabbix-daily-reporting); ETC=$(dr_prefix /etc/zabbix-daily-reporting); STATE=$(dr_prefix /var/lib/zabbix-daily-reporting); SYSTEMD=$(dr_prefix /etc/systemd/system); BACKUPS=$(dr_prefix /var/backups/zabbix-daily-reporting)
installed_config_rc=0
if [[ -f $ETC/report.json ]]; then set +e; dr_validate_config "$SOURCE" "$ETC/report.json"; installed_config_rc=$?; set -e; ((installed_config_rc==0)) && dr_info 'INSTALLED_CONFIG=PASS' || dr_warn 'INSTALLED_CONFIG=WARNING'; else dr_info 'INSTALLED_CONFIG=NOT_INSTALLED'; fi
dr_info "OS=$DR_OS"; dr_info "PYTHON=$($DR_PYTHON --version 2>&1)"; dr_info 'CUSTOM_REPORT_PREFLIGHT=PASS'
set +e; "$DR_PYTHON" "$SOURCE/bin/native_preflight.py"; native_rc=$?; set -e
((native_rc==0)) || dr_warn 'native PDF prerequisites are incomplete; custom reporting remains installable'
if ((PREFLIGHT)); then ((installed_config_rc==0)) && { dr_info 'RESULT=PASS'; exit 0; } || { dr_info 'RESULT=WARNING'; exit 2; }; fi
dr_root
((installed_config_rc==0)) || dr_fail 'installed report.json is invalid; application was not changed'
STAMP=$(date -u +%Y%m%d-%H%M%S-%N); BACKUP="$BACKUPS/$STAMP"
install -d -m 0750 "$BACKUP" "$ETC" "$STATE" "$STATE/reports" "$SYSTEMD"
[[ -f $ETC/report.json ]] && dr_validate_config "$SOURCE" "$ETC/report.json"
if [[ -z ${DAILY_REPORTING_ROOT:-} ]]; then
  getent group zabbix-report >/dev/null || groupadd --system zabbix-report
  getent passwd zabbix-report >/dev/null || useradd --system --gid zabbix-report --home-dir /var/lib/zabbix-daily-reporting --shell /sbin/nologin zabbix-report
  chown -R zabbix-report:zabbix-report "$STATE"
fi
[[ -d $APP ]] && cp -a "$APP" "$BACKUP/application"
STAGE="${APP}.install.$$"; trap 'rm -rf -- "$STAGE"' EXIT; rm -rf -- "$STAGE"; install -d -m 0755 "$STAGE"; cp -a "$SOURCE/." "$STAGE/"
find "$STAGE" -type d -exec chmod 0755 {} +; find "$STAGE" -type f -exec chmod 0644 {} +; chmod 0755 "$STAGE"/bin/*.py
if [[ -d $APP ]]; then mv "$APP" "${APP}.replaced-$STAMP"; fi
mv "$STAGE" "$APP"
if [[ ! -f $ETC/report.json ]]; then install -m 0640 "$CONFIG_SOURCE" "$ETC/report.json"; else cp -a "$ETC/report.json" "$BACKUP/report.json"; dr_info 'CONFIG=PRESERVED'; fi
dr_validate_config "$APP" "$ETC/report.json"
if [[ ! -f $ETC/secrets.env ]]; then
  install -m 0600 /dev/null "$ETC/secrets.env"
  printf '%s\n' '# Never commit this file.' 'ZABBIX_API_TOKEN=' 'ZABBIX_API_USER=' 'ZABBIX_API_PASSWORD=' 'DAILY_REPORT_SMTP_PASSWORD=' >>"$ETC/secrets.env"
else cp -a "$ETC/secrets.env" "$BACKUP/secrets.env"; dr_info 'SECRETS=PRESERVED'; fi
install -m 0644 "$SOURCE/systemd/zabbix-daily-report.service" "$SYSTEMD/zabbix-daily-report.service"
CALENDAR=$(dr_schedule_calendar "$APP" "$ETC/report.json"); TIMER_STAGE="$BACKUP/zabbix-daily-report.timer"
sed "s|__DAILY_REPORTING_ON_CALENDAR__|$CALENDAR|" "$SOURCE/systemd/zabbix-daily-report.timer" >"$TIMER_STAGE"
grep -Fxq "OnCalendar=$CALENDAR" "$TIMER_STAGE" || dr_fail 'timer schedule rendering failed'
install -m 0644 "$TIMER_STAGE" "$SYSTEMD/zabbix-daily-report.timer"; dr_info "TIMER_SCHEDULE=$CALENDAR"
if [[ -z ${DAILY_REPORTING_ROOT:-} ]]; then
  chown root:zabbix-report "$ETC/report.json" "$ETC/secrets.env"; chmod 0640 "$ETC/report.json"; chmod 0600 "$ETC/secrets.env"
  command -v restorecon >/dev/null && restorecon -RF "$APP" "$ETC" "$STATE" "$SYSTEMD/zabbix-daily-report."{service,timer} || true
  timer_active=0; systemctl is-active --quiet zabbix-daily-report.timer && timer_active=1 || true
  systemctl daemon-reload
  if ((ENABLE_TIMER)); then dr_has_credentials "$ETC/secrets.env" || dr_fail 'refusing to enable timer: API credentials are absent'; systemctl enable --now zabbix-daily-report.timer; systemctl restart zabbix-daily-report.timer; elif ((timer_active)); then systemctl restart zabbix-daily-report.timer; else dr_warn 'timer installed but not enabled; populate secrets.env then rerun with --enable-timer'; fi
fi
if ((APPLY_NATIVE)); then
  [[ -z ${DAILY_REPORTING_ROOT:-} ]] || dr_fail '--apply-native-config is unavailable with DAILY_REPORTING_ROOT'
  ((native_rc==0)) || dr_fail 'native prerequisites must pass before server configuration can be applied'
  SERVER=/etc/zabbix/zabbix_server.conf; DROPIN=/etc/zabbix/zabbix_server.conf.d/daily-reporting.conf
  [[ -r $SERVER ]] || dr_fail 'zabbix_server.conf missing'
  grep -Eq '^\s*Include=.*/zabbix_server\.conf\.d/\*\.conf' "$SERVER" || dr_fail 'server configuration does not include zabbix_server.conf.d/*.conf'
  BASELINE="$BACKUPS/native-baseline"; dr_capture_native_state "$BASELINE" "$DROPIN"; dr_capture_native_state "$BACKUP/native-before" "$DROPIN"
  web_url=$($DR_PYTHON -c 'import json,sys;print(json.load(open(sys.argv[1]))["native_pdf"]["web_service_url"])' "$ETC/report.json")
  writers=$($DR_PYTHON -c 'import json,sys;print(json.load(open(sys.argv[1]))["native_pdf"]["report_writers"])' "$ETC/report.json")
  printf 'WebServiceURL=%s\nStartReportWriters=%s\n' "$web_url" "$writers" >"$DROPIN"
  zabbix_server -T -c "$SERVER" >/dev/null || { dr_restore_native_state "$BACKUP/native-before" "$DROPIN"; dr_fail 'zabbix_server configuration validation failed and proposed drop-in was reverted'; }
  systemctl enable --now zabbix-web-service; systemctl restart zabbix-server
  dr_info 'NATIVE_SERVER_CONFIGURATION=APPLIED'
fi
dr_info "APPLICATION=$APP"; dr_info "CONFIG=$ETC/report.json"; dr_info "STATE=$STATE"; dr_info "BACKUP=$BACKUP"; dr_info 'RESULT=PASS'

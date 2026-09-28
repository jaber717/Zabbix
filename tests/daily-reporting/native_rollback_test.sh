#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)

run_case(){
  local prior=$1 tmp rootfs backups baseline dropin
  tmp=$(mktemp -d); rootfs="$tmp/root"; backups="$rootfs/var/backups/zabbix-daily-reporting"; baseline="$backups/native-baseline"; dropin="$rootfs/etc/zabbix/zabbix_server.conf.d/daily-reporting.conf"
  install -d "$backups" "$(dirname "$dropin")" "$rootfs/etc/zabbix-daily-reporting" "$rootfs/var/lib/zabbix-daily-reporting/reports" "$rootfs/etc/zabbix"
  printf 'preserve-config\n' >"$rootfs/etc/zabbix-daily-reporting/report.json"; printf 'preserve-secret\n' >"$rootfs/etc/zabbix-daily-reporting/secrets.env"; printf 'preserve-report\n' >"$rootfs/var/lib/zabbix-daily-reporting/reports/report.html"; printf 'Include=/etc/zabbix/zabbix_server.conf.d/*.conf\n' >"$rootfs/etc/zabbix/zabbix_server.conf"
  if [[ $prior == PRESENT ]]; then printf 'WebServiceURL=https://previous.example/report\nStartReportWriters=7\n# exact previous bytes\n' >"$dropin"; cp "$dropin" "$tmp/expected.conf"; fi
  # shellcheck source=scripts/lib/daily-reporting-common.sh
  source "$ROOT/scripts/lib/daily-reporting-common.sh"
  dr_capture_native_state "$baseline" "$dropin"
  printf 'WebServiceURL=http://127.0.0.1:10053/report\nStartReportWriters=1\n' >"$dropin"
  dr_capture_native_state "$baseline" "$dropin"
  printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$*" >>"%s"\nexit 0\n' "$tmp/zabbix-server.log" >"$tmp/fake-zabbix-server"; chmod 0755 "$tmp/fake-zabbix-server"
  printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$*" >>"%s"\nexit 0\n' "$tmp/systemctl.log" >"$tmp/fake-systemctl"; chmod 0755 "$tmp/fake-systemctl"
  DAILY_REPORTING_ROOT="$rootfs" DAILY_REPORTING_ZABBIX_SERVER_BIN="$tmp/fake-zabbix-server" DAILY_REPORTING_SYSTEMCTL="$tmp/fake-systemctl" bash "$ROOT/scripts/rollback_daily_reporting.sh" --confirm >"$tmp/output"
  if [[ $prior == PRESENT ]]; then cmp -s "$tmp/expected.conf" "$dropin"; grep -Fq "NATIVE_CONFIGURATION=RESTORED:$dropin" "$tmp/output"; else [[ ! -e $dropin ]]; grep -Fq "NATIVE_CONFIGURATION=REMOVED:$dropin" "$tmp/output"; fi
  grep -Fq -- "-T -c $rootfs/etc/zabbix/zabbix_server.conf" "$tmp/zabbix-server.log"
  grep -Fxq 'restart zabbix-server' "$tmp/systemctl.log"
  grep -Fq 'NATIVE_CONFIGURATION_VALIDATION=PASS' "$tmp/output"
  grep -Fxq 'preserve-config' "$rootfs/etc/zabbix-daily-reporting/report.json"; grep -Fxq 'preserve-secret' "$rootfs/etc/zabbix-daily-reporting/secrets.env"; grep -Fxq 'preserve-report' "$rootfs/var/lib/zabbix-daily-reporting/reports/report.html"
  printf 'NATIVE_ROLLBACK_%s=PASS\n' "$prior"
}

run_case PRESENT
run_case ABSENT
printf 'NATIVE_BASELINE_DOUBLE_CAPTURE=PASS\n'
printf 'RESULT=PASS\n'

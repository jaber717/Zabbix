#!/usr/bin/env bash
# LAB validation: READ-ONLY against the LAB Zabbix. Writes nothing, sends nothing, enables nothing.
#   ZABBIX_HARDWARE_URL_LAB=http://192.168.1.91/ ZABBIX_HARDWARE_TOKEN_LAB=... release/validate-lab.sh [prefix]
# Exit 0 only when every check passed. Output is evidence for the Codex acceptance checklist.
set -uo pipefail
PREFIX="${1:-/opt/netops-hardware-health}"
CUR="$PREFIX/current"; [ -d "$CUR" ] || CUR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-python3}"
: "${ZABBIX_HARDWARE_URL_LAB:?set ZABBIX_HARDWARE_URL_LAB}"; : "${ZABBIX_HARDWARE_TOKEN_LAB:?set ZABBIX_HARDWARE_TOKEN_LAB (never put it in a file in the repository)}"
export ZABBIX_HARDWARE_URL_LAB ZABBIX_HARDWARE_TOKEN_LAB
RC=0
step() { echo; echo "== $1"; shift; "$@"; local r=$?; echo "-- exit $r"; [ "$r" = 0 ] || RC=1; }
H="$PY $CUR/hardware_audit.py --base $CUR"
step "offline: vendor definitions import check"      $H vendors check
step "offline: simulated trigger scenarios"            $H vendors simulate
step "offline: notification message contract"          $H vendors messages
step "LAB: simulator host/items/triggers + notification isolation (read-only)" $H --env lab labsim
step "LAB: authoritative-evidence availability (read-only)" $H --env lab synthetic audit-probe
step "LAB: hardware action plan (read-only; shows what apply WOULD do)" $H --env lab action plan
step "LAB: template plan for cisco-iosxe (read-only)"  $H --env lab template plan --definition cisco-iosxe
echo
[ "$RC" = 0 ] && echo "LAB VALIDATION: ALL CHECKS PASSED (no live Telegram delivery was tested)" || echo "LAB VALIDATION: FAILURES ABOVE"
exit "$RC"

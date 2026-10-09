#!/usr/bin/env bash
# Verify an installed deployment OFFLINE: manifest integrity, config presence and validity, offline self-tests, permissions. Contacts nothing.
#   verify-deployment.sh [prefix]
set -uo pipefail
PREFIX="${1:-/opt/netops-hardware-health}"
PY="${PYTHON:-python3}"
FAIL=0
ok()   { echo "  ok    $1"; }
bad()  { echo "  FAIL  $1"; FAIL=1; }
[ -L "$PREFIX/current" ] && ok "current release: $(readlink "$PREFIX/current")" || { bad "no current release"; exit 1; }
CUR="$PREFIX/current"
( cd "$CUR" && sha256sum -c MANIFEST.sha256 >/dev/null 2>&1 ) && ok "release manifest verified" || bad "release manifest does not verify (files changed or missing)"
[ -d "$PREFIX/config" ] && ok "config directory present" || bad "config directory missing"
[ -d "$PREFIX/state" ] && ok "state directory present" || bad "state directory missing"
PERM="$(stat -c %a "$PREFIX/state" 2>/dev/null || echo ?)"
[ "$PERM" = "700" ] && ok "state directory is 0700" || bad "state directory permissions are $PERM (want 700)"
LOOSE="$(find "$PREFIX/state" "$PREFIX/backups" \( -type f -perm /077 -o -type d -perm /077 \) 2>/dev/null | head -3)"
[ -z "$LOOSE" ] && ok "ownership records and backups are private (no group/other access)" || bad "ownership/backup state is accessible by group or others: $(echo $LOOSE | tr '\n' ' ')"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' && ok "Python >= 3.9" || bad "Python 3.9+ missing"
"$PY" -c 'import yaml' 2>/dev/null && ok "PyYAML importable" || bad "PyYAML missing"
for sub in "vendors check" "vendors simulate" "vendors messages"; do
  "$PY" "$CUR/hardware_audit.py" --base "$CUR" $sub >/dev/null 2>&1 && ok "hardware_audit.py $sub" || bad "hardware_audit.py $sub"
done
"$PY" "$CUR/hardware_audit.py" --base "$CUR" --version 2>&1 | grep -q "hardware-health $(cat "$CUR/VERSION")" && ok "CLI reports version $(cat "$CUR/VERSION")" || bad "CLI version does not match VERSION file"
# the shipped hardware action must still be inactive: this release never enables it
grep -rEq 'enabled:[[:space:]]*true' "$PREFIX/config" 2>/dev/null && bad "a config file requests enabled: true" || ok "no config requests the action to be enabled"
# no credentials stored in the deployment
if grep -rEIl '(api[_-]?token|password)[[:space:]]*[:=][[:space:]]*["'"'"']?[A-Za-z0-9+/=_-]{16,}' "$PREFIX/config" >/dev/null 2>&1; then bad "a config file looks like it holds a credential (use environment variables)"; else ok "no credential-like values in config"; fi
[ "$FAIL" = 0 ] && echo "DEPLOYMENT VERIFIED (offline checks only; this does not test Zabbix)" || echo "DEPLOYMENT VERIFICATION FAILED"
exit "$FAIL"

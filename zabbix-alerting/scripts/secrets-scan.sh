#!/usr/bin/env bash
# Scan the release scope (working tree AND full Git history of zabbix-alerting/ and handover/) for secrets.
#   ./scripts/secrets-scan.sh            exit 0 = nothing found, 1 = findings (printed with file, never the secret)
set -u   # (no pipefail: grep returns 1 on "no match", which is the good case)
cd "$(dirname "${BASH_SOURCE[0]}")/.."
ROOT="$(git rev-parse --show-toplevel)"
PATHS=("zabbix-alerting" "handover")
cd "$ROOT"

# name|regex  (findings print only name + location, never the matching text)
PATTERNS=(
  'telegram-bot-token|[0-9]{8,10}:[A-Za-z0-9_-]{34,36}'
  'private-key|-----BEGIN [A-Z ]*PRIVATE KEY-----'
  'aws-access-key|AKIA[0-9A-Z]{16}'
  'github-token|gh[pousr]_[A-Za-z0-9]{30,}'
  'bearer-token|[Bb]earer [A-Za-z0-9._-]{24,}'
  'zabbix-api-token|(ZABBIX|ZBX)[A-Z_]*TOKEN[ ]*[=:][ ]*["'"'"']?[0-9a-f]{32,}'
  'password-assignment|([Pp]ass(word|wd)?|PASS|secret|SECRET)[A-Za-z_]*[ ]*[=:][ ]*["'"'"']?[A-Za-z0-9!@#$%^&*+/=_-]{8,}'
  'snmp-key|(auth|priv)[A-Za-z_]*(pass|key)[A-Za-z_]*[ ]*[=:][ ]*["'"'"']?[A-Za-z0-9!@#$%^&*+/=_-]{8,}'
)
# harmless matches: documentation of variable NAMES, placeholders, test fixtures
ALLOW='(\{\$SNMPV3_(AUTH|PRIV)_PASS\}|ZABBIX_TOKEN_(LAB|PRODUCTION)=$|token_env|password_env|ZBX_PASSWORD|GRAFANA_PASSWORD|tok-lab|demo|PASSWORD=<|SNMPV3_AUTH_PASS|SNMPV3_PRIV_PASS|passphrases|\.password|"password"|password:|passwords)'

fail=0
scan_text() { # label ; text on stdin (read ONCE, then every pattern is run on it)
  local label="$1" n=0 name rx hits buf
  buf="$(cat)"
  for p in "${PATTERNS[@]}"; do
    name="${p%%|*}"; rx="${p#*|}"
    hits=$(printf '%s
' "$buf" | grep -aEn -- "$rx" | grep -avE "$ALLOW" | wc -l)
    if [ "$hits" != 0 ]; then echo "FINDING [$name] x$hits in $label"; n=$((n+hits)); fi
  done
  return $(( n > 0 ? 1 : 0 ))
}

echo "== working tree"
while IFS= read -r f; do
  [ -f "$f" ] || continue
  case "$f" in *.pyc) continue;; esac
  # the scanner itself lists the patterns
  case "$f" in zabbix-alerting/scripts/secrets-scan.sh) continue;; esac
  scan_text "$f" < "$f" || fail=1
done < <(git ls-files -- "${PATHS[@]}"; git ls-files --others --exclude-standard -- "${PATHS[@]}")

echo "== forbidden files"
bad=$(git ls-files -- "${PATHS[@]}" | grep -E '(^|/)\.env$|\.pem$|\.key$|id_rsa|credstore|\.p12$|state/backups' || true)
[ -n "$bad" ] && { echo "FINDING forbidden file tracked: $bad"; fail=1; }

echo "== git history (all branches, these paths)"
for c in $(git rev-list --all -- "${PATHS[@]}"); do
  git show --format= --unified=0 "$c" -- "${PATHS[@]}" 2>/dev/null | grep -a '^+' | grep -av '^+++' \
    | sed 's/^+//' | scan_text "commit ${c:0:9}" || fail=1
done

echo "== untracked / ignored secrets files present locally"
ls zabbix-alerting/.env 2>/dev/null && echo "NOTE: zabbix-alerting/.env exists locally (git-ignored; never committed)"

if [ "$fail" = 0 ]; then echo "SECRETS SCAN: PASS (no findings)"; else echo "SECRETS SCAN: FAIL"; fi
exit $fail

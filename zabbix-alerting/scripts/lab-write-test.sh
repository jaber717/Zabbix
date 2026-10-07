#!/usr/bin/env bash
# The one command that completes real-Zabbix validation once a WRITE-capable LAB API token exists.
#
#   cp .env.example .env ; edit ZABBIX_URL_LAB / ZABBIX_TOKEN_LAB (token of a user that may write)
#   ./scripts/lab-write-test.sh
#
# It exercises the full operator workflow on a harmless policy (examples/lab-validation.yaml) and
# prints PASS/FAIL for every step. It only ever talks to --env lab.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"
if [ -f "$HERE/.env" ]; then set -a; . "$HERE/.env"; set +a; fi
CFG="examples/lab-validation.yaml"
pass=0; fail=0
step() { # name expected_rc must_contain cmd...
  local name="$1" want_rc="$2" needle="$3"; shift 3
  local out rc
  out="$("$@" 2>&1)"; rc=$?
  if [ "$rc" = "$want_rc" ] && { [ -z "$needle" ] || grep -qF -- "$needle" <<<"$out"; }; then
    echo "PASS  $name"; pass=$((pass+1))
  else
    echo "FAIL  $name (rc=$rc, wanted rc=$want_rc, text '$needle')"
    echo "$out" | sed 's/^/      /' | tail -25
    fail=$((fail+1))
  fi
}

step "1  --check (all PASS)"                      0 "RESULT: PASS"                ./apply.sh --env lab --config "$CFG" --check
step "2  --dry-run shows pending ADDs"            0 "DRY RUN"                     ./apply.sh --env lab --config "$CFG" --dry-run
step "3  apply"                                   0 "verification plan is empty"  ./apply.sh --env lab --config "$CFG"
step "4  --dry-run is clean (idempotent)"         0 "No changes required."        ./apply.sh --env lab --config "$CFG" --dry-run
step "5  second apply does nothing"               0 "No changes required."        ./apply.sh --env lab --config "$CFG"
step "6  YAML threshold change is planned 70->75" 0 "live '70' -> git '75'"       ./apply.sh --env lab --config examples/lab-validation-changed.yaml --dry-run
step "7  apply the change"                        0 "verification plan is empty"  ./apply.sh --env lab --config examples/lab-validation-changed.yaml
step "8  revert"                                  0 "verification plan is empty"  ./apply.sh --env lab --config "$CFG"
step "9  dry-run clean after revert"              0 "No changes required."        ./apply.sh --env lab --config "$CFG" --dry-run
step "10 objects exist and values arrive in Zabbix" 0 "RESULT: PASS"              python3 scripts/lab_verify_objects.py --env lab --config "$CFG"
step "11 remove everything this tool manages"     0 "verification plan is empty"  ./apply.sh --env lab --config examples/empty.yaml --allow-empty
step "12 dry-run clean after removal"             0 "No changes required."        ./apply.sh --env lab --config examples/empty.yaml --dry-run

echo
echo "REAL LAB WRITE VALIDATION: $pass passed, $fail failed"
[ "$fail" = 0 ]

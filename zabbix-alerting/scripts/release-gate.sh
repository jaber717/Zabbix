#!/usr/bin/env bash
# Release gate for zabbix-alerting: run before any candidate is handed to the tester and before any tag is created.
#   ./scripts/release-gate.sh            offline gates only (no Zabbix, no network)
# Gates: (1) syntax of every Python file / shell script in the repository, (2) full unit-test suite, (3) secret scan of tree + history,
#        (4) ShellCheck if installed (reported as NOT RUN otherwise - never silently skipped).
# Exit 0 only when gates 1-3 pass (and gate 4 passes or is honestly reported as not run).
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 2
PY="${PYTHON:-python3}"
rc=0
echo "== 1/4 syntax (python + bash -n, whole repository)"
"$PY" scripts/check-syntax.py || rc=1
echo "== 2/4 unit tests"
"$PY" -m unittest discover -s tests -t . 2>&1 | tail -4 ; [ "${PIPESTATUS[0]}" = 0 ] || rc=1
echo "== 3/4 secret scan"
bash scripts/secrets-scan.sh || rc=1
echo "== 4/4 shellcheck"
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck --version | sed -n 2p
  ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo ..)"
  git -C "$ROOT" ls-files 'zabbix-alerting/*.sh' | while read -r f; do echo "$ROOT/$f"; done | xargs shellcheck -S warning || rc=1
else
  echo "SHELLCHECK: NOT RUN (executable not installed). Not a pass."
fi
[ $rc = 0 ] && echo "RELEASE GATE: PASS" || echo "RELEASE GATE: FAIL"
exit $rc

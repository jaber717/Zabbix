#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

readonly PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
CONFIG=/root/zabbix-install.env
fail() { printf 'ZABBIX DEPLOYMENT VERIFICATION: FAIL\nDETAIL: %s\n' "$*" >&2; exit 1; }
cleanup() {
  if [[ -n ${runtime_dir:-} && -d $runtime_dir && $runtime_dir == /run/zabbix-release.* ]]; then
    rm -rf -- "$runtime_dir"
  fi
}
trap cleanup EXIT HUP INT TERM

if [[ ${1:-} == --config && -n ${2:-} && $# -eq 2 ]]; then
  CONFIG=$2
elif (($#)); then
  fail "usage: sudo ./verify.sh [--config /root/zabbix-install.env]"
fi
[[ $EUID -eq 0 ]] || fail "root is required"
python3 "$PROJECT_ROOT/scripts/repository-scan.py" \
  || fail "repository secret/data/payload scan failed"
runtime_dir=$(mktemp -d /run/zabbix-release.XXXXXX)
python3 "$PROJECT_ROOT/scripts/prepare-runtime.py" \
  --config "$CONFIG" --output "$runtime_dir" --repo-root "$PROJECT_ROOT" \
  || fail "runtime input validation failed"
release_root=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["offline_bundle_root"])' "$runtime_dir/paths.json")
if [[ -z $release_root && -f /etc/zabbix-offline/bundle-root ]]; then
  IFS= read -r release_root </etc/zabbix-offline/bundle-root
fi
[[ -n $release_root ]] || fail "OFFLINE_BUNDLE_ROOT must identify the installed bundle during verification"
"$PROJECT_ROOT/installer/bootstrap.sh" \
  --release-root "$release_root" \
  --vars "$runtime_dir/vars.json" \
  --db-password-file "$runtime_dir/db-password" \
  --verify-only || fail "one or more required checks failed"
printf 'ZABBIX DEPLOYMENT VERIFICATION: PASS\n'

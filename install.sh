#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

readonly PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
CONFIG=/root/zabbix-install.env

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
cleanup() {
  if [[ -n ${runtime_dir:-} && -d $runtime_dir && $runtime_dir == /run/zabbix-release.* ]]; then
    rm -rf -- "$runtime_dir"
  fi
}
trap cleanup EXIT HUP INT TERM

if [[ ${1:-} == --config && -n ${2:-} && $# -eq 2 ]]; then
  CONFIG=$2
elif (($#)); then
  fail "usage: sudo ./install.sh [--config /root/zabbix-install.env]"
fi
[[ $EUID -eq 0 ]] || fail "root is required"
source "$PROJECT_ROOT/installer/lib/platform.sh"
validate_rhel_platform || exit 1
[[ -f $CONFIG ]] || fail "runtime configuration not found: $CONFIG"
python3 "$PROJECT_ROOT/scripts/repository-scan.py" --runtime-config "$CONFIG" \
  || fail "repository secret/data/payload scan failed"
runtime_dir=$(mktemp -d /run/zabbix-release.XXXXXX)
python3 "$PROJECT_ROOT/scripts/prepare-runtime.py" \
  --config "$CONFIG" --output "$runtime_dir" --repo-root "$PROJECT_ROOT"

mode=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["install_mode"])' "$runtime_dir/paths.json")
release_root=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["offline_bundle_root"])' "$runtime_dir/paths.json")
# Connected installs always stage from this clean source commit. The installed
# pointer remains useful to verify.sh, but is never an implicit build input.
if [[ $mode == connected && -z $release_root ]]; then
  stage_root="/var/tmp/zabbix-release-build-$(date -u +%Y%m%dT%H%M%SZ)"
  BASEOS_REPO=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["baseos_repo"])' "$runtime_dir/paths.json") \
  APPSTREAM_REPO=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["appstream_repo"])' "$runtime_dir/paths.json") \
  OUTPUT_DIR=$stage_root "$PROJECT_ROOT/scripts/stage-offline-bundle.sh"
  release_root="$stage_root/release-tree"
fi
[[ -n $release_root ]] || fail "OFFLINE_BUNDLE_ROOT is required for airgapped installation"
release_root=$(readlink -f -- "$release_root")
[[ -d $release_root ]] || fail "offline bundle root does not exist: $release_root"

printf 'PASS: immutable inputs accepted\n'
"$PROJECT_ROOT/installer/bootstrap.sh" \
  --release-root "$release_root" \
  --vars "$runtime_dir/vars.json" \
  --db-password-file "$runtime_dir/db-password"
install -d -o root -g root -m 0750 /etc/zabbix-offline
printf '%s\n' "$release_root" >/etc/zabbix-offline/bundle-root
chmod 0644 /etc/zabbix-offline/bundle-root
printf 'PASS: installation completed\n'

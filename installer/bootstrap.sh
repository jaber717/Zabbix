#!/usr/bin/env bash
set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly REPO_FILE=/etc/yum.repos.d/zabbix-offline.repo

RELEASE_ROOT="$(cd -- "$SCRIPT_DIR/.." 2>/dev/null && pwd -P || true)"
VARS_FILE=""
DB_PASSWORD_FILE=""
MODE=install

usage() {
  cat <<'USAGE'
Usage: bootstrap.sh --release-root PATH --vars PATH --db-password-file PATH [MODE]

Modes:
  --preflight-only  Verify immutable inputs and target compatibility; make no changes.
  --check           Run the installer in Ansible check mode on an already bootstrapped target.
  --verify-only     Run only the installed-target verification playbook.

Normal install configures one file:// repository, installs ansible-core from it,
and hands off to the Ansible site playbook. Every DNF command disables all other
repositories.
USAGE
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

while (($#)); do
  case "$1" in
    --release-root)
      (($# >= 2)) || die "--release-root requires a value"
      RELEASE_ROOT=$2
      shift 2
      ;;
    --vars)
      (($# >= 2)) || die "--vars requires a value"
      VARS_FILE=$2
      shift 2
      ;;
    --db-password-file)
      (($# >= 2)) || die "--db-password-file requires a value"
      DB_PASSWORD_FILE=$2
      shift 2
      ;;
    --preflight-only)
      MODE=preflight
      shift
      ;;
    --check)
      MODE=check
      shift
      ;;
    --verify-only)
      MODE=verify
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

[[ $EUID -eq 0 ]] || die "bootstrap must run as root"
source "$SCRIPT_DIR/lib/platform.sh"
validate_rhel_platform || exit 1
[[ -n $RELEASE_ROOT ]] || die "release root is required"
RELEASE_ROOT="$(readlink -f -- "$RELEASE_ROOT")"
[[ -d $RELEASE_ROOT ]] || die "release root does not exist: $RELEASE_ROOT"
[[ -n $VARS_FILE && -f $VARS_FILE ]] || die "an environment variables file is required"
VARS_FILE="$(readlink -f -- "$VARS_FILE")"
[[ -n $DB_PASSWORD_FILE && -f $DB_PASSWORD_FILE ]] || die "database password input file is required"
DB_PASSWORD_FILE="$(readlink -f -- "$DB_PASSWORD_FILE")"

for required in BUILD-INFO.json SHA256SUMS rpm-lockfile.txt compat/zabbix-7.0.yaml repository/repodata/repomd.xml; do
  [[ -e $RELEASE_ROOT/$required ]] || die "offline bundle input is missing: $required"
done
[[ -f $SCRIPT_DIR/MANIFEST.sha256 ]] || die "installer manifest is missing"

(
  cd -- "$RELEASE_ROOT"
  sha256sum --quiet -c SHA256SUMS
) || die "offline bundle checksum verification failed"
(
  cd -- "$SCRIPT_DIR"
  sha256sum --quiet -c MANIFEST.sha256
) || die "installer checksum verification failed"

python3 "$SCRIPT_DIR/lib/validate_bundle.py" "$RELEASE_ROOT" "$RHEL_VERSION_ID"
python3 - "$DB_PASSWORD_FILE" <<'PY'
import json
import os
import stat
import sys

secret_path = sys.argv[1]
secret_stat = os.stat(secret_path)
if secret_stat.st_uid != 0:
    raise SystemExit("database password input must be owned by root")
if stat.S_IMODE(secret_stat.st_mode) & 0o077:
    raise SystemExit("database password input must not be group/world accessible")
PY

[[ $(getenforce) == Enforcing ]] || die "SELinux must already be Enforcing"

if [[ $MODE == preflight ]]; then
  printf 'RESULT=PASS_PREFLIGHT\n'
  exit 0
fi

if [[ $MODE == install ]]; then
  tmp_repo=$(mktemp /run/zabbix-offline.repo.XXXXXX)
  trap 'rm -f -- "${tmp_repo:-}"' EXIT
  cat >"$tmp_repo" <<EOF
[zabbix-offline]
name=Zabbix Controlled Offline Repository
baseurl=file://$RELEASE_ROOT/repository
enabled=1
gpgcheck=1
repo_gpgcheck=0
gpgkey=file://$RELEASE_ROOT/repository/gpg/RPM-GPG-KEY-redhat-release
       file://$RELEASE_ROOT/repository/gpg/RPM-GPG-KEY-ZABBIX-B5333005
       file://$RELEASE_ROOT/repository/gpg/RPM-GPG-KEY-ZABBIX-08EFA7DD
metadata_expire=-1
EOF
  install -o root -g root -m 0644 "$tmp_repo" "$REPO_FILE"
  rm -f -- "$tmp_repo"
  trap - EXIT

  dnf --assumeyes --disablerepo='*' --enablerepo=zabbix-offline \
    --setopt=install_weak_deps=False install ansible-core
else
  [[ -f $REPO_FILE ]] || die "check/verify mode requires an already bootstrapped offline repository"
  command -v ansible-playbook >/dev/null || die "check/verify mode requires installed ansible-core"
fi

export ANSIBLE_CONFIG="$SCRIPT_DIR/ansible.cfg"
export ZABBIX_DB_PASSWORD_FILE="$DB_PASSWORD_FILE"

playbook="$SCRIPT_DIR/playbooks/site.yml"
extra_args=()
case "$MODE" in
  check)
    extra_args+=(--check --diff)
    ;;
  verify)
    playbook="$SCRIPT_DIR/playbooks/verify.yml"
    ;;
esac

ansible-playbook "$playbook" \
  --inventory "$SCRIPT_DIR/inventory/hosts.yml" \
  --extra-vars "@$VARS_FILE" \
  --extra-vars "offline_release_root=$RELEASE_ROOT" \
  --extra-vars "validated_rhel_version=$RHEL_VERSION_ID" \
  "${extra_args[@]}"

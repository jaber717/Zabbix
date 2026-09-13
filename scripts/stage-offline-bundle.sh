#!/usr/bin/env bash
set -Eeuo pipefail

readonly PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
[[ $EUID -eq 0 ]] || { printf 'FAIL: run as root on an authorized subscribed RHEL 9.6 staging system\n' >&2; exit 1; }
for command in dnf subscription-manager git; do
  command -v "$command" >/dev/null 2>&1 || { printf 'FAIL: missing staging prerequisite: %s\n' "$command" >&2; exit 1; }
done
grep -Fqx 'Red Hat Enterprise Linux release 9.6 (Plow)' /etc/redhat-release \
  || { printf 'FAIL: staging host must be RHEL 9.6\n' >&2; exit 1; }
[[ $(uname -m) == x86_64 ]] || { printf 'FAIL: staging host must be x86_64\n' >&2; exit 1; }
git_cmd=(git -c "safe.directory=$PROJECT_ROOT" -C "$PROJECT_ROOT")
commit="$("${git_cmd[@]}" rev-parse --verify HEAD)"
[[ -z $("${git_cmd[@]}" status --porcelain --untracked-files=no) ]] \
  || { printf 'FAIL: offline bundles must be staged from a clean commit\n' >&2; exit 1; }
epoch="$("${git_cmd[@]}" show -s --format=%ct "$commit")"
sudo -n subscription-manager identity >/dev/null \
  || { printf 'FAIL: a usable RHEL subscription identity is required\n' >&2; exit 1; }
dnf --assumeyes --releasever=9.6 --disablerepo='*' \
  --enablerepo=rhel-9-for-x86_64-baseos-rpms \
  --enablerepo=rhel-9-for-x86_64-appstream-rpms \
  --setopt=install_weak_deps=False install \
  curl createrepo_c modulemd-tools gnupg2 rpm jq dnf-plugins-core sudo git-core
for command in curl createrepo_c modifyrepo_c modulemd-merge gpg rpm rpmkeys sha256sum tar jq sudo; do
  command -v "$command" >/dev/null 2>&1 || { printf 'FAIL: missing staging prerequisite after approved install: %s\n' "$command" >&2; exit 1; }
done
export BUILD_GIT_COMMIT="$commit" BUILD_GIT_DIRTY=false SOURCE_DATE_EPOCH="$epoch"
exec "$PROJECT_ROOT/build/build.sh"

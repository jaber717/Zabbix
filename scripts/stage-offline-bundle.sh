#!/usr/bin/env bash
set -Eeuo pipefail

readonly PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
[[ $EUID -eq 0 ]] || { printf 'FAIL: run as root on an authorized RHEL 9.x staging system\n' >&2; exit 1; }
source "$PROJECT_ROOT/installer/lib/platform.sh"
validate_rhel_platform || exit 1
for command in dnf subscription-manager git; do
  command -v "$command" >/dev/null 2>&1 || { printf 'FAIL: missing staging prerequisite: %s\n' "$command" >&2; exit 1; }
done
git_cmd=(git -c "safe.directory=$PROJECT_ROOT" -C "$PROJECT_ROOT")
commit="$("${git_cmd[@]}" rev-parse --verify HEAD)"
[[ -z $("${git_cmd[@]}" status --porcelain) ]] \
  || { printf 'FAIL: offline bundles must be staged from a clean commit\n' >&2; exit 1; }
epoch="$("${git_cmd[@]}" show -s --format=%ct "$commit")"
detect_release_context || exit 1
export BASEOS_REPO=${BASEOS_REPO:-rhel-9-for-x86_64-baseos-rpms}
export APPSTREAM_REPO=${APPSTREAM_REPO:-rhel-9-for-x86_64-appstream-rpms}
for repo in "$BASEOS_REPO" "$APPSTREAM_REPO"; do
  [[ $repo =~ ^[A-Za-z0-9_-]+$ && $repo != zabbix-offline ]] || { printf 'FAIL: invalid RHEL repository ID\n' >&2; exit 1; }
done
[[ $BASEOS_REPO != "$APPSTREAM_REPO" ]] || { printf 'FAIL: BaseOS and AppStream must be distinct\n' >&2; exit 1; }
# Repository content access is the requirement; Satellite/RHUI mirrors need
# not expose a local RHSM consumer identity. Fail closed on actual access.
dnf "${HOST_RELEASE_ARGS[@]}" --disablerepo='*' \
  --enablerepo="$BASEOS_REPO" --enablerepo="$APPSTREAM_REPO" \
  --setopt="$BASEOS_REPO.skip_if_unavailable=False" \
  --setopt="$APPSTREAM_REPO.skip_if_unavailable=False" makecache --refresh
dnf --assumeyes "${HOST_RELEASE_ARGS[@]}" --disablerepo='*' \
  --enablerepo="$BASEOS_REPO" \
  --enablerepo="$APPSTREAM_REPO" \
  --setopt=install_weak_deps=False install \
  curl createrepo_c modulemd-tools gnupg2 rpm jq dnf-plugins-core sudo git-core
for command in curl createrepo_c modifyrepo_c modulemd-merge gpg rpm rpmkeys sha256sum tar jq sudo; do
  command -v "$command" >/dev/null 2>&1 || { printf 'FAIL: missing staging prerequisite after approved install: %s\n' "$command" >&2; exit 1; }
done
export BUILD_GIT_COMMIT="$commit" BUILD_GIT_DIRTY=false SOURCE_DATE_EPOCH="$epoch"
export LOCK_MODE=resolve
exec "$PROJECT_ROOT/build/build.sh"

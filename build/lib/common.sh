#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
PROFILE_PATH=${PROFILE_PATH:-"$PROJECT_ROOT/compat/zabbix-7.0.yaml"}
eval "$(python3 "$PROJECT_ROOT/build/lib/profile.py" env "$PROFILE_PATH")"

mapfile -t ZABBIX_PACKAGES < <(python3 "$PROJECT_ROOT/build/lib/profile.py" list "$PROFILE_PATH" zabbix.packages)
mapfile -t RUNTIME_PACKAGES < <(python3 "$PROJECT_ROOT/build/lib/profile.py" list "$PROFILE_PATH" runtime_packages)
mapfile -t PYTHON_PACKAGES < <(python3 "$PROJECT_ROOT/build/lib/profile.py" list "$PROFILE_PATH" python.packages)

log() { printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "required command unavailable: $1"; }

host_rpm_hash() {
  rpm -qa --qf '%{NAME}|%{EPOCHNUM}|%{VERSION}|%{RELEASE}|%{ARCH}\n' | LC_ALL=C sort | sha256sum | awk '{print $1}'
}

host_module_hash() {
  sudo -n sh -c "find /etc/dnf/modules.d -maxdepth 1 -type f -print0 2>/dev/null | sort -z | xargs -0 -r sha256sum | sha256sum" | awk '{print $1}'
}

safe_remove_root() {
  local path=${1:-}
  case "$path" in
    /var/lib/zabbix-offline-build/m1-[A-Za-z0-9._-]*) sudo -n rm -rf -- "$path" ;;
    *) die "refusing unsafe cleanup path: ${path:-<empty>}" ;;
  esac
}

source_dnf() {
  sudo -n dnf \
    --installroot="$CLEAN_ROOT" \
    --releasever="$RHEL_RELEASE" \
    --forcearch="$TARGET_ARCH" \
    --setopt=module_platform_id=platform:el9 \
    --disablerepo='*' \
    --enablerepo="$BASEOS_REPO" \
    --enablerepo="$APPSTREAM_REPO" \
    --repofrompath="$ZABBIX_REPO,$ZABBIX_REPO_URL" \
    --enablerepo="$ZABBIX_REPO" \
    --setopt="$ZABBIX_REPO.gpgcheck=1" \
    --setopt="$ZABBIX_REPO.gpgkey=$ZABBIX_KEY_URL" \
    "$@"
}

local_dnf() {
  local root=$1 repo=$2
  shift 2
  sudo -n dnf \
    --installroot="$root" \
    --releasever="$RHEL_RELEASE" \
    --forcearch="$TARGET_ARCH" \
    --setopt=module_platform_id=platform:el9 \
    --disablerepo='*' \
    --repofrompath=m1-local,"file://$repo" \
    --enablerepo=m1-local \
    --setopt=m1-local.gpgcheck=1 \
    --setopt=m1-local.repo_gpgcheck=0 \
    --setopt="m1-local.gpgkey=file://$repo/gpg/RPM-GPG-KEY-redhat-release file://$repo/gpg/RPM-GPG-KEY-ZABBIX-B5333005" \
    "$@"
}

assert_source_repos() {
  local output=$1
  grep -q "$BASEOS_REPO" "$output" || die "BaseOS source absent"
  grep -q "$APPSTREAM_REPO" "$output" || die "AppStream source absent"
  grep -q "$ZABBIX_REPO" "$output" || die "Zabbix source absent"
  if grep -Eqi 'netbox-offline|epel|remi|pgdg|rocky|alma|centos' "$output"; then
    die "unapproved repository visible in clean source context"
  fi
}

zabbix_specs() {
  local package
  for package in "${ZABBIX_PACKAGES[@]}"; do
    printf '%s-%s-%s\n' "$package" "$ZABBIX_VERSION" "$ZABBIX_RELEASE"
  done
}

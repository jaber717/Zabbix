#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd -P)/lib/common.sh"

BUILD_OUTPUT=${1:?build output required}
RESULTS=${2:-"$BUILD_OUTPUT/evidence/negative-tests.txt"}
REPO="$BUILD_OUTPUT/repository"
RELEASE="$BUILD_OUTPUT/release-tree"
LOCK="$BUILD_OUTPUT/rpm-lockfile.candidate.txt"
[[ -d "$REPO" && -d "$RELEASE" && -f "$LOCK" ]] || die "incomplete build output"

NEG_ROOT="/var/lib/zabbix-offline-build/m1-negative-$(date -u +%Y%m%dT%H%M%SZ)-$$"
CLEAN_ROOT="$NEG_ROOT/assert-root"
cleanup() { safe_remove_root "$NEG_ROOT"; }
trap cleanup EXIT INT TERM
sudo -n install -d -m 0755 "$NEG_ROOT"
sudo -n chown "$(id -u):$(id -g)" "$NEG_ROOT"
: > "$RESULTS"

record() { printf '%s=%s\n' "$1" "$2" | tee -a "$RESULTS"; }

cp "$LOCK" "$NEG_ROOT/drift.lock"
printf 'unexpected-0:0-0.noarch\tnoarch\tunapproved\t0\n' >> "$NEG_ROOT/drift.lock"
if cmp -s "$LOCK" "$NEG_ROOT/drift.lock"; then record LOCK_DRIFT FAIL; exit 1; else record LOCK_DRIFT PASS; fi

{
  echo 'repo id repo name'
  printf '%s\n%s\n%s\n%s\n%s\n' "$BASEOS_REPO" "$APPSTREAM_REPO" "$ZABBIX_REPO" "$NON_SUPPORTED_REPO" netbox-offline-base
} > "$NEG_ROOT/repos.txt"
if (assert_source_repos "$NEG_ROOT/repos.txt") >/dev/null 2>&1; then record UNRELATED_REPO FAIL; exit 1; else record UNRELATED_REPO PASS; fi

awk -F '\t' -v OFS='\t' -v repo="$NON_SUPPORTED_REPO" '
  NR == 1 {print; next}
  !changed && $1 !~ /^fping-/ {$3=repo; changed=1}
  {print}
' "$LOCK" > "$NEG_ROOT/non-supported-scope.lock"
if (assert_lock_source_policy "$NEG_ROOT/non-supported-scope.lock") >/dev/null 2>&1; then record NON_SUPPORTED_SCOPE FAIL; exit 1; else record NON_SUPPORTED_SCOPE PASS; fi

cp -al "$REPO" "$NEG_ROOT/missing-repo"
missing=$(find "$NEG_ROOT/missing-repo/rpm" -name "zabbix-server-pgsql-$ZABBIX_VERSION-$ZABBIX_RELEASE.*.rpm" -print -quit)
[[ -n "$missing" ]] || die "negative missing-RPM fixture absent"
rm -f -- "$missing"
sudo -n install -d -m 0755 "$NEG_ROOT/missing-root/var/lib/rpm" "$NEG_ROOT/missing-download"
sudo -n rpm --root "$NEG_ROOT/missing-root" --initdb
set +e
local_dnf "$NEG_ROOT/missing-root" "$NEG_ROOT/missing-repo" download --destdir="$NEG_ROOT/missing-download" "zabbix-server-pgsql-$ZABBIX_VERSION-$ZABBIX_RELEASE" > "$NEG_ROOT/missing-rpm.log" 2>&1
rc=$?
set -e
if ((rc == 0)); then record MISSING_RPM FAIL; exit 1; else record MISSING_RPM PASS; fi

good_rpm=$(find "$REPO/rpm" -type f -name '*.rpm' -print -quit)
cp "$good_rpm" "$NEG_ROOT/corrupted.rpm"
printf '\000' | dd of="$NEG_ROOT/corrupted.rpm" bs=1 seek=8192 conv=notrunc status=none
set +e
rpmkeys --checksig "$NEG_ROOT/corrupted.rpm" > "$NEG_ROOT/corrupt-signature.log" 2>&1
rc=$?
set -e
if ((rc == 0)); then record CORRUPTED_RPM FAIL; exit 1; else record CORRUPTED_RPM PASS; fi

cp -al "$REPO" "$NEG_ROOT/no-module-repo"
rm -rf -- "$NEG_ROOT/no-module-repo/repodata"
createrepo_c "$NEG_ROOT/no-module-repo" > "$NEG_ROOT/no-module-createrepo.log" 2>&1
sudo -n install -d -m 0755 "$NEG_ROOT/no-module-root/var/lib/rpm"
sudo -n rpm --root "$NEG_ROOT/no-module-root" --initdb
local_dnf "$NEG_ROOT/no-module-root" "$NEG_ROOT/no-module-repo" module list postgresql > "$NEG_ROOT/no-module-query.log" 2>&1 || true
if grep -Eq "postgresql[[:space:]]+$POSTGRESQL_STREAM([[:space:]]|$)" "$NEG_ROOT/no-module-query.log"; then record MISSING_MODULE_METADATA FAIL; exit 1; else record MISSING_MODULE_METADATA PASS; fi

cp -al "$RELEASE" "$NEG_ROOT/forbidden-release"
mkdir -p "$NEG_ROOT/forbidden-release/.git"
printf 'fixture\n' > "$NEG_ROOT/forbidden-release/.git/config"
set +e
"$PROJECT_ROOT/build/verify-build.sh" "$NEG_ROOT/forbidden-release" "$LOCK" > "$NEG_ROOT/forbidden-file.log" 2>&1
rc=$?
set -e
if ((rc == 0)); then record FORBIDDEN_FILE FAIL; exit 1; else record FORBIDDEN_FILE PASS; fi

cp -al "$RELEASE" "$NEG_ROOT/leak-release"
printf 'ENDPOINT=192.168.1.10\n' > "$NEG_ROOT/leak-release/compat/runtime.conf"
set +e
"$PROJECT_ROOT/build/verify-build.sh" "$NEG_ROOT/leak-release" "$LOCK" > "$NEG_ROOT/lab-leakage.log" 2>&1
rc=$?
set -e
if ((rc == 0)); then record LAB_LEAKAGE FAIL; exit 1; else record LAB_LEAKAGE PASS; fi

UNTRUSTED_SIGDB="$NEG_ROOT/untrusted-root/var/lib/rpm"
sudo -n install -d -m 0755 "$UNTRUSTED_SIGDB"
sudo -n rpm --dbpath="$UNTRUSTED_SIGDB" --initdb
set +e
sudo -n rpmkeys --dbpath="$UNTRUSTED_SIGDB" --checksig "$good_rpm" > "$NEG_ROOT/untrusted-signature.log" 2>&1
rc=$?
set -e
if ((rc == 0)); then record UNTRUSTED_SIGNATURE FAIL; exit 1; else record UNTRUSTED_SIGNATURE PASS; fi

record RESULT PASS

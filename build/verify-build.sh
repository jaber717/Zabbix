#!/usr/bin/env bash
set -euo pipefail

RELEASE_TREE=${1:?release tree required}
LOCKFILE=${2:?lockfile required}
[[ -d "$RELEASE_TREE" && -f "$LOCKFILE" ]] || { echo "invalid verification inputs" >&2; exit 2; }

fail() { echo "VERIFY_FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

mapfile -t top < <(find "$RELEASE_TREE" -mindepth 1 -maxdepth 1 -printf '%f\n' | LC_ALL=C sort)
allowed=$'BUILD-INFO.json\nMANIFEST.txt\nRPM-MANIFEST.txt\nSHA256SUMS\ncompat\ndocs\nintegration\nrepository\nrpm-lockfile.txt'
[[ $(printf '%s\n' "${top[@]}") == "$allowed" ]] || fail "release top-level allow-list mismatch"
pass "release top-level allow-list"

if find "$RELEASE_TREE" -type f \( -name '*.pyc' -o -name '*~' -o -name '*.swp' -o -name '*.src.rpm' -o -name '*.key' -o -name '*.pem' -o -name '*.p12' -o -name '*.pfx' \) -print -quit | grep -q .; then
  fail "forbidden file pattern"
fi
if find "$RELEASE_TREE" -type d \( -name .git -o -name __pycache__ -o -name .venv -o -name work -o -name out \) -print -quit | grep -q .; then
  fail "forbidden directory pattern"
fi
pass "artifact file hygiene"

if grep -RIlE --exclude='SHA256SUMS' --exclude='MANIFEST.txt' --exclude='RPM-MANIFEST.txt' --exclude='rpm-lockfile.txt' \
  'BEGIN (RSA|OPENSSH|EC|DSA) PRIVATE KEY|(^|[^A-Za-z])(password|api[_-]?token|secret)[[:space:]]*=' "$RELEASE_TREE" | grep -q .; then
  fail "credential-like content"
fi
pass "secret-pattern scan"

for runtime_path in "$RELEASE_TREE/compat" "$RELEASE_TREE/integration" "$RELEASE_TREE/repository/zabbix-offline.repo"; do
  if grep -RIE 'JaberLAB|netbox-demo|192\.168\.|LXC 9000|LAB-MOCK|LAB-EMULATED' "$runtime_path" >/dev/null 2>&1; then
    fail "lab identifier in production runtime path"
  fi
done
pass "runtime lab-leakage scan"

(cd "$RELEASE_TREE" && find . -type f -printf '%P\n' | LC_ALL=C sort) > "$RELEASE_TREE/../manifest.actual"
cmp -s "$RELEASE_TREE/MANIFEST.txt" "$RELEASE_TREE/../manifest.actual" || fail "manifest coverage mismatch"
rm -f "$RELEASE_TREE/../manifest.actual"
pass "manifest bidirectional coverage"

(cd "$RELEASE_TREE" && sha256sum -c SHA256SUMS >/dev/null) || fail "release file checksum mismatch"
pass "release SHA256SUMS"
cmp -s "$RELEASE_TREE/rpm-lockfile.txt" "$LOCKFILE" || fail "release lockfile mismatch"
cmp -s "$RELEASE_TREE/RPM-MANIFEST.txt" "$LOCKFILE" || fail "RPM manifest mismatch"
pass "RPM lock and manifest"

[[ $(find "$RELEASE_TREE/repository/rpm" -type f -name '*.rpm' | wc -l) -eq $(($(wc -l < "$LOCKFILE") - 1)) ]] || fail "RPM count mismatch"
[[ -f "$RELEASE_TREE/repository/repodata/repomd.xml" ]] || fail "repomd missing"
grep -q 'type="modules"' "$RELEASE_TREE/repository/repodata/repomd.xml" || fail "module metadata missing from repomd"
pass "repository and modular metadata present"

echo "RESULT=PASS"

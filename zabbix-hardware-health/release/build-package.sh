#!/usr/bin/env bash
# Build the OFFLINE release package: a single tarball + its SHA256 file. Needs only bash, tar, sha256sum. Contacts nothing.
#   release/build-package.sh [output-dir]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$HERE/dist}"
VERSION="$(sed -n 's/^VERSION = "\(.*\)"$/\1/p' "$HERE/hwh/__init__.py")"
[ -n "$VERSION" ] || { echo "cannot read VERSION from hwh/__init__.py" >&2; exit 1; }
NAME="netops-hardware-health-$VERSION"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/$NAME" "$OUT"
for p in hardware_audit.py requirements.txt README.md hwh vendors docs tests release; do
  [ -e "$HERE/$p" ] && cp -R "$HERE/$p" "$STAGE/$NAME/$p"
done
# operator-editable configuration ships as DEFAULTS; install.sh copies it to <prefix>/config only when that does not exist yet
cp -R "$HERE/config" "$STAGE/$NAME/config.defaults"
find "$STAGE/$NAME" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$STAGE/$NAME" -name '*.pyc' -delete 2>/dev/null || true
rm -rf "$STAGE/$NAME/state" "$STAGE/$NAME/evidence" "$STAGE/$NAME/dist"
echo "$VERSION" > "$STAGE/$NAME/VERSION"
# no credentials in the package (defence in depth; the repository never holds any)
if grep -rEIl '(api[_-]?token|password|secret)[[:space:]]*[:=][[:space:]]*["'"'"']?[A-Za-z0-9+/=_-]{16,}' "$STAGE/$NAME" >/dev/null 2>&1; then
  echo "REFUSING TO BUILD: a file looks like it contains a credential:" >&2
  grep -rEIl '(api[_-]?token|password|secret)[[:space:]]*[:=][[:space:]]*["'"'"']?[A-Za-z0-9+/=_-]{16,}' "$STAGE/$NAME" >&2 || true
  exit 1
fi
( cd "$STAGE/$NAME" && find . -type f ! -name MANIFEST.sha256 | LC_ALL=C sort | xargs sha256sum > MANIFEST.sha256 )
tar -C "$STAGE" -czf "$OUT/$NAME.tar.gz" "$NAME"
( cd "$OUT" && sha256sum "$NAME.tar.gz" > "$NAME.tar.gz.sha256" )
echo "built $OUT/$NAME.tar.gz"
cat "$OUT/$NAME.tar.gz.sha256"

#!/usr/bin/env bash
# Install or upgrade NETOPS Hardware Health from the offline package. Idempotent. Never touches Zabbix, never enables anything.
#   install.sh <package.tar.gz> [--prefix DIR]
# Layout:  <prefix>/releases/<version>/   immutable, manifest-verified code
#          <prefix>/current  -> releases/<version>       <prefix>/previous -> the release replaced by the last switch
#          <prefix>/config/  operator configuration (created from defaults ONCE, never overwritten)
#          <prefix>/state/   backups, ownership records, ledgers (survives upgrades and rollbacks)
set -euo pipefail
PKG=""; PREFIX="/opt/netops-hardware-health"
while [ $# -gt 0 ]; do
  case "$1" in
    --prefix) PREFIX="$2"; shift 2 ;;
    -*) echo "unknown option $1" >&2; exit 2 ;;
    *) PKG="$1"; shift ;;
  esac
done
[ -n "$PKG" ] && [ -f "$PKG" ] || { echo "usage: install.sh <package.tar.gz> [--prefix DIR]" >&2; exit 2; }

# 1. package integrity (the .sha256 file must sit next to the tarball)
if [ -f "$PKG.sha256" ]; then
  ( cd "$(dirname "$PKG")" && sha256sum -c "$(basename "$PKG").sha256" >/dev/null ) || { echo "PACKAGE CHECKSUM MISMATCH - refusing to install" >&2; exit 1; }
  echo "package checksum OK"
else
  echo "no $PKG.sha256 next to the package - refusing to install an unverified package" >&2; exit 1
fi

# 2. prerequisites (offline: nothing is downloaded)
PY="${PYTHON:-python3}"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || { echo "Python 3.9+ is required (set PYTHON=...)" >&2; exit 1; }
"$PY" -c 'import yaml' 2>/dev/null || { echo "PyYAML (>=6.0,<7.0) is not installed. Install it from your own wheelhouse: $PY -m pip install --no-index --find-links <wheelhouse> 'PyYAML>=6.0,<7.0'" >&2; exit 1; }

# 3. unpack to a staging dir, verify the manifest BEFORE the release becomes visible
STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
tar -C "$STAGE" -xzf "$PKG"
SRC="$(find "$STAGE" -mindepth 1 -maxdepth 1 -type d | head -1)"
[ -f "$SRC/VERSION" ] && [ -f "$SRC/MANIFEST.sha256" ] || { echo "package is malformed (no VERSION / MANIFEST)" >&2; exit 1; }
( cd "$SRC" && sha256sum -c MANIFEST.sha256 >/dev/null ) || { echo "MANIFEST MISMATCH - refusing to install" >&2; exit 1; }
VERSION="$(cat "$SRC/VERSION")"
case "$VERSION" in *[!A-Za-z0-9._-]*|"") echo "bad version string" >&2; exit 1 ;; esac

mkdir -p "$PREFIX/releases" "$PREFIX/state" "$PREFIX/backups"
chmod 700 "$PREFIX/state" "$PREFIX/backups" 2>/dev/null || true
DEST="$PREFIX/releases/$VERSION"
if [ -e "$DEST" ]; then
  ( cd "$DEST" && sha256sum -c MANIFEST.sha256 >/dev/null ) && echo "release $VERSION is already installed and verified" || { echo "release $VERSION exists but fails its manifest - remove it by hand and re-run" >&2; exit 1; }
else
  mv "$SRC" "$DEST"
fi

# 4. configuration: created from defaults once; an existing config is NEVER overwritten
if [ ! -d "$PREFIX/config" ]; then
  cp -R "$DEST/config.defaults" "$PREFIX/config"
  echo "created $PREFIX/config from the shipped defaults (review before use)"
else
  echo "existing $PREFIX/config kept unchanged"
  for f in "$DEST/config.defaults/"*; do
    [ -e "$PREFIX/config/$(basename "$f")" ] || { cp -R "$f" "$PREFIX/config/"; echo "added new default $(basename "$f")"; }
  done
fi
ln -sfn "$PREFIX/config" "$DEST/config"
ln -sfn "$PREFIX/state" "$DEST/state"

# 5. offline self-test of the release BEFORE switching to it
( cd "$DEST" && "$PY" hardware_audit.py --base "$DEST" vendors check >/dev/null && "$PY" hardware_audit.py --base "$DEST" vendors simulate >/dev/null \
  && "$PY" hardware_audit.py --base "$DEST" vendors messages >/dev/null ) || { echo "release self-test FAILED - not switching" >&2; exit 1; }

# 6. atomic switch, remembering the previous release for rollback
OLD=""
[ -L "$PREFIX/current" ] && OLD="$(readlink "$PREFIX/current")"
if [ "$OLD" != "$DEST" ]; then
  [ -n "$OLD" ] && ln -sfn "$OLD" "$PREFIX/previous"
  ln -sfn "$DEST" "$PREFIX/current.new" && mv -T "$PREFIX/current.new" "$PREFIX/current"
fi
echo "installed hardware-health $VERSION at $PREFIX/current"
echo "next: $PREFIX/current/release/verify-deployment.sh $PREFIX"

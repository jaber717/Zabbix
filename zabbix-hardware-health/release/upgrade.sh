#!/usr/bin/env bash
# Safe upgrade: back up config and state first, then install the new release (same verification as install.sh). Rollback: rollback.sh.
#   upgrade.sh <package.tar.gz> [--prefix DIR]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="/opt/netops-hardware-health"
ARGS=("$@")
for i in "${!ARGS[@]}"; do [ "${ARGS[$i]}" = "--prefix" ] && PREFIX="${ARGS[$((i+1))]}"; done
[ -L "$PREFIX/current" ] || { echo "nothing installed at $PREFIX (use install.sh)" >&2; exit 1; }
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BK="$PREFIX/backups/pre-upgrade-$STAMP.tar.gz"
( umask 077; tar -C "$PREFIX" -czf "$BK" config state 2>/dev/null )
chmod 600 "$BK" 2>/dev/null || true
echo "backup written: $BK (config + state)"
echo "previous release: $(readlink "$PREFIX/current")"
exec bash "$HERE/install.sh" "$@"

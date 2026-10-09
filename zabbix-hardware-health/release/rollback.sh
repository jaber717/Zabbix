#!/usr/bin/env bash
# Roll the CODE back to the previous release (atomic symlink switch). Config and state are untouched; restore a pre-upgrade backup by hand only if
# the upgrade changed them (tar -xzf <prefix>/backups/pre-upgrade-*.tar.gz -C <prefix>). This does not change anything in Zabbix: to undo Zabbix-side
# objects use `hardware_audit.py action rollback` / `template rollback` / the synthetic emergency-disable plan.
#   rollback.sh [--prefix DIR]
set -euo pipefail
PREFIX="/opt/netops-hardware-health"
[ "${1:-}" = "--prefix" ] && PREFIX="$2"
[ -L "$PREFIX/previous" ] || { echo "no previous release recorded at $PREFIX" >&2; exit 1; }
PREV="$(readlink "$PREFIX/previous")"; CUR="$(readlink "$PREFIX/current")"
[ -d "$PREV" ] || { echo "previous release directory is missing: $PREV" >&2; exit 1; }
( cd "$PREV" && sha256sum -c MANIFEST.sha256 >/dev/null ) || { echo "previous release fails its manifest - refusing to switch" >&2; exit 1; }
ln -sfn "$PREV" "$PREFIX/current.new" && mv -T "$PREFIX/current.new" "$PREFIX/current"
ln -sfn "$CUR" "$PREFIX/previous"
echo "rolled back: current -> $PREV (was $CUR)"

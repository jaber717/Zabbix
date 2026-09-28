#!/usr/bin/env bash
set -Eeuo pipefail
DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P); ROOT=$(cd "$DIR/.." && pwd -P)
VERSION=$(tr -d '[:space:]' <"$ROOT/reporting/daily-reporting/VERSION"); NAME="zabbix-daily-reporting-$VERSION"; DIST="$ROOT/dist"; WORK=$(mktemp -d)
trap 'rm -rf -- "$WORK"' EXIT
mkdir -p "$WORK/$NAME/scripts/lib" "$WORK/$NAME/reporting" "$WORK/$NAME/docs" "$DIST"
cp -a "$ROOT/reporting/daily-reporting" "$WORK/$NAME/reporting/"
cp -a "$ROOT/scripts/install_daily_reporting.sh" "$ROOT/scripts/verify_daily_reporting.sh" "$ROOT/scripts/rollback_daily_reporting.sh" "$ROOT/scripts/build_offline_bundle.sh" "$WORK/$NAME/scripts/"
cp -a "$ROOT/scripts/daily-reporting-release.sha256" "$WORK/$NAME/scripts/"
cp -a "$ROOT/scripts/lib/daily-reporting-common.sh" "$WORK/$NAME/scripts/lib/"
cp -a "$ROOT/docs/DAILY-REPORTING.md" "$WORK/$NAME/docs/"
(cd "$WORK/$NAME" && find . -type f ! -name MANIFEST.sha256 -print0 | sort -z | xargs -0 sha256sum) >"$WORK/$NAME/MANIFEST.sha256"
find "$WORK/$NAME/scripts" "$WORK/$NAME/reporting/daily-reporting/bin" -type f \( -name '*.sh' -o -name '*.py' \) -exec chmod 0755 {} +
tar --sort=name --mtime='UTC 2020-01-01' --owner=0 --group=0 --numeric-owner -C "$WORK" -czf "$DIST/$NAME.tar.gz" "$NAME"
(cd "$DIST" && sha256sum "$NAME.tar.gz" >"$NAME.tar.gz.sha256")
printf 'BUNDLE=%s\nCHECKSUM=%s\nRESULT=PASS\n' "$DIST/$NAME.tar.gz" "$DIST/$NAME.tar.gz.sha256"

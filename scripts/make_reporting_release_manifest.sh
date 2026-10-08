#!/usr/bin/env bash
# Regenerates scripts/daily-reporting-release.sha256 from the committed (LF) blobs of the release files.
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P); cd "$ROOT"
files=(docs/DAILY-REPORTING.md scripts/build_offline_bundle.sh scripts/fetch_reporting_wheels.sh scripts/install_daily_reporting.sh scripts/verify_daily_reporting.sh scripts/rollback_daily_reporting.sh scripts/lib/daily-reporting-common.sh)
while IFS= read -r f; do files+=("$f"); done < <(git ls-files reporting/daily-reporting docs/reporting-suite | sort)
for f in "${files[@]}"; do printf '%s  %s\n' "$(git show ":$f" | sha256sum | awk '{print $1}')" "$f"; done >scripts/daily-reporting-release.sha256
echo "entries=$(wc -l <scripts/daily-reporting-release.sha256)"

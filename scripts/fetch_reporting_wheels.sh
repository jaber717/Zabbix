#!/usr/bin/env bash
# Run on a CONNECTED workstation. Downloads the pinned wheels listed in reporting/daily-reporting/wheels.lock into
# reporting/daily-reporting/wheelhouse/ and verifies every SHA-256. The offline bundle then carries them to the isolated server.
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
LOCK="$ROOT/reporting/daily-reporting/wheels.lock"; OUT="$ROOT/reporting/daily-reporting/wheelhouse"
mkdir -p "$OUT"
while read -r sum name url; do
  [[ -z ${sum:-} || $sum == \#* ]] && continue
  if [[ ! -f $OUT/$name ]] || ! echo "$sum  $OUT/$name" | sha256sum -c --status; then
    curl -fsSL --retry 3 -o "$OUT/$name.part" "$url"; mv "$OUT/$name.part" "$OUT/$name"
  fi
  echo "$sum  $OUT/$name" | sha256sum -c --status || { echo "HASH MISMATCH: $name" >&2; rm -f "$OUT/$name"; exit 1; }
  echo "OK $name"
done <"$LOCK"
echo 'RESULT=PASS'

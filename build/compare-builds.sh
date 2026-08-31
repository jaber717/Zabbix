#!/usr/bin/env bash
set -euo pipefail

LEFT=${1:?first build output required}
RIGHT=${2:?second build output required}
OUT=${3:-/dev/stdout}

{
  echo "LEFT=$LEFT"
  echo "RIGHT=$RIGHT"
  cmp "$LEFT/rpm-lockfile.candidate.txt" "$RIGHT/rpm-lockfile.candidate.txt"
  echo "RPM_LOCK=PASS"
  cmp "$LEFT/evidence/module-metadata-sha256.txt" "$RIGHT/evidence/module-metadata-sha256.txt"
  echo "MODULE_METADATA=PASS"
  cmp "$LEFT/release-tree/MANIFEST.txt" "$RIGHT/release-tree/MANIFEST.txt"
  echo "ARTIFACT_ALLOW_LIST=PASS"
  cmp "$LEFT/release-tree/RPM-MANIFEST.txt" "$RIGHT/release-tree/RPM-MANIFEST.txt"
  echo "RPM_CHECKSUMS_AND_PROVENANCE=PASS"
  echo "RESULT=PASS"
} > "$OUT"

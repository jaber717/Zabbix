#!/usr/bin/env bash
# digests-to-overlay.sh — translate overlay/.digests.lock into a transient
# compose fragment that pins every service's `image:` to its sha256 digest.
# Emits YAML on stdout. Called by compose-up.sh at run time.
set -euo pipefail

cd "$(dirname "$0")/.."
LOCK=overlay/.digests.lock
if [ ! -s "$LOCK" ]; then
  echo "no digest lock" >&2
  exit 1
fi

digest_for() {
  grep -E "^$1=" "$LOCK" | head -1 | cut -d= -f2-
}

printf 'services:\n'
map=(
  "kafka=apache/kafka:4.3.1"
  "redis=valkey/valkey:9.0"
  "clickhouse=clickhouse/clickhouse-server:26.8"
  "traefik=traefik:v3.7"
  "kafka-ui=kafbat/kafka-ui:v1.5.0"
  "akvorado-orchestrator=quay.io/akvorado/akvorado:${AKVORADO_VERSION:-2026.10.0}"
  "akvorado-inlet=quay.io/akvorado/akvorado:${AKVORADO_VERSION:-2026.10.0}"
  "akvorado-outlet=quay.io/akvorado/akvorado:${AKVORADO_VERSION:-2026.10.0}"
  "akvorado-console=quay.io/akvorado/akvorado:${AKVORADO_VERSION:-2026.10.0}"
)
for pair in "${map[@]}"; do
  svc="${pair%%=*}"; img="${pair#*=}"
  d=$(digest_for "$img" || true)
  if [ -n "$d" ]; then
    printf '  %s:\n    image: %s\n' "$svc" "$d"
  fi
done

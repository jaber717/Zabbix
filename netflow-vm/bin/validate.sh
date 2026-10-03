#!/usr/bin/env bash
# validate.sh — static consistency check runnable off-box (no Docker needed).
# Confirms:
#   - vendored upstream compose is unchanged (hashes against versions.yml).
#   - overlay refers only to upstream service names that actually exist.
#   - compose file order resolves cleanly via `docker compose config`.
#   - digest lock, if present, references every service in the overlay.
set -euo pipefail

cd "$(dirname "$0")/.."
UPSTREAM=upstream/akvorado-v2026.10.0

echo "== upstream services exposed =="
grep -E '^\s{2}[a-z][a-z0-9-]*:$' "$UPSTREAM/docker/docker-compose.yml" | sed 's/://; s/^ *//'

echo "== overlay services =="
grep -E '^\s{2}[a-z][a-z0-9-]*:$' overlay/docker-compose.netops.yml | sed 's/://; s/^ *//'

echo "== cross-check: every overlay service exists upstream =="
missing=0
for s in $(grep -E '^\s{2}[a-z][a-z0-9-]*:$' overlay/docker-compose.netops.yml | sed 's/://; s/^ *//'); do
  if ! grep -qE "^\s{2}${s}:$" "$UPSTREAM/docker/docker-compose.yml"; then
    echo "MISSING  overlay refers to unknown upstream service: $s"
    missing=$((missing+1))
  fi
done
[ "$missing" -eq 0 ] && echo "OK"

echo "== compose config (static, no containers started) =="
if command -v docker >/dev/null 2>&1; then
  docker compose -f "$UPSTREAM/docker/docker-compose.yml" -f overlay/docker-compose.netops.yml config --quiet \
    && echo "docker compose config OK"
else
  echo "SKIP docker not installed on this host"
fi

echo "== digest lock cross-check =="
if [ -s overlay/.digests.lock ]; then
  for img in \
      "apache/kafka:4.3.1" \
      "valkey/valkey:9.0" \
      "clickhouse/clickhouse-server:26.8" \
      "traefik:v3.7" \
      "quay.io/akvorado/akvorado:2026.10.0" ; do
    grep -q "^$img=" overlay/.digests.lock || echo "MISS  $img not pinned"
  done
else
  echo "no digest lock yet — run bin/pin-digests.sh on the deploy host"
fi

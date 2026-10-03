#!/usr/bin/env bash
# pin-digests.sh — pull the stack and record immutable sha256 digests.
# Idempotent. Writes `../overlay/.digests.lock` which `compose-up.sh` consumes.
#
# After this runs the next `compose-up.sh` substitutes digest-pinned image refs
# via `yq`, so the stack is never pulled from a floating tag again until a
# human explicitly bumps the vendored version.
set -euo pipefail

cd "$(dirname "$0")/.."
UPSTREAM=upstream/akvorado-v2026.10.0
: "${AKVORADO_VERSION:=2026.10.0}"

# Pull everything referenced by versions.yml, then capture digests.
docker compose -f "$UPSTREAM/docker/docker-compose.yml" --project-directory "$UPSTREAM" pull --quiet \
    kafka redis clickhouse traefik akvorado-orchestrator akvorado-inlet akvorado-outlet akvorado-console

LOCK=overlay/.digests.lock
TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT

cat > "$TMP" <<EOF
# Immutable Akvorado NetFlow deployment digests
# Captured $(date -u +%Y-%m-%dT%H:%M:%SZ) by pin-digests.sh
# Source: upstream/$UPSTREAM
# Akvorado release: v${AKVORADO_VERSION}
# Change ONLY by re-running pin-digests.sh after a vendored-upstream bump.
EOF

for img in \
    "apache/kafka:4.3.1" \
    "valkey/valkey:9.0" \
    "clickhouse/clickhouse-server:26.8" \
    "traefik:v3.7" \
    "kafbat/kafka-ui:v1.5.0" \
    "quay.io/akvorado/akvorado:${AKVORADO_VERSION}" ; do
  d=$(docker image inspect --format '{{index .RepoDigests 0}}' "$img" 2>/dev/null || true)
  if [ -z "$d" ]; then
    echo "WARN  no digest for $img (image not present locally; pull failed?)" >&2
    echo "# WARN missing: $img" >> "$TMP"
    continue
  fi
  printf '%s=%s\n' "$img" "$d" >> "$TMP"
done

# Rotate previous digest-lock for one-step rollback.
if [ -f "$LOCK" ]; then
  cp "$LOCK" "overlay/.digests.lock.prev"
fi
install -m 0644 "$TMP" "$LOCK"
echo "wrote $LOCK:"
grep -v '^#' "$LOCK" || true

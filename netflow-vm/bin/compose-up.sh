#!/usr/bin/env bash
# compose-up.sh — bring the Akvorado stack up with the vendored upstream
# compose + the NetOps overlay. Idempotent. Prefers digest-pinned refs when
# overlay/.digests.lock is present.
set -euo pipefail

cd "$(dirname "$0")/.."
UPSTREAM=upstream/akvorado-v2026.10.0

# Ensure the dedicated LV mount points exist with correct SELinux labels.
install -d -m 0750 /var/lib/akvorado/data/clickhouse
install -d -m 0750 /var/lib/akvorado/data/kafka
chcon -R -t container_file_t /var/lib/akvorado/data 2>/dev/null || true

# Compose file chain: upstream base + overlay. Keep upstream's own layering
# (prometheus, loki, grafana, ipinfo, local) off by default; enable per-site
# via netflow-vm/overlay/env.netops.
export COMPOSE_PROJECT_NAME=akvorado
export COMPOSE_FILE="$UPSTREAM/docker/docker-compose.yml:overlay/docker-compose.netops.yml"

if [ -s overlay/.digests.lock ]; then
  echo "Using digest-pinned images from overlay/.digests.lock"
  # Pass the resolved digest for each image via docker-compose extra_hosts /
  # service `image:` overrides. We do this by generating a tiny supplemental
  # compose file at /run.
  bin/digests-to-overlay.sh > /run/akvorado-digests.yml
  export COMPOSE_FILE="$COMPOSE_FILE:/run/akvorado-digests.yml"
else
  echo "WARN  overlay/.digests.lock missing — running from upstream tags."
  echo "WARN  run bin/pin-digests.sh to make this deployment immutable."
fi

docker compose --project-directory "$UPSTREAM" up -d
docker compose --project-directory "$UPSTREAM" ps

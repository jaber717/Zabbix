#!/usr/bin/env bash
# release-consistency.sh — FAIL if any provisioning file references the OLD
# runtime stack, or if a README command points at a path whose parent
# directory doesn't exist. Run from the repo root OR from inside netflow-vm/.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail=0
emit() { echo "FAIL  $*"; fail=$((fail+1)); }
ok()   { echo "ok    $*"; }

# 1. Forbidden *operational* substrings. Patterns match the way the OLD stack
#    would appear in a provisioning file. Human-written phrases that merely
#    DENY the old thing (e.g. "no Zookeeper") are tagged on the line with
#    `# BAN:keep` and the grep below filters those out.
FORBIDDEN=(
  '1\.11\.4'                 # old Akvorado tag
  'cp-kafka'                 # Confluent Kafka image
  'confluentinc/'            # anything from Confluent registry
  '24\.8\.4'                 # old ClickHouse tag
  'podman-compose'           # we chose Docker Engine + compose plugin
  'netflow-vm/compose/'      # old compose dir replaced by vendored upstream + overlay
  'zookeeper'                # image / env refs are lowercase; prose "Zookeeper" filtered via BAN:keep
)
SCAN_PATHS=(
  provisioning/
  overlay/
  bin/
  flow-api/
  README.md
  docs/
)
for p in "${SCAN_PATHS[@]}"; do
  [ -e "$p" ] || continue
  for pat in "${FORBIDDEN[@]}"; do
    hit=$(grep -r --line-number -iE "$pat" "$p" 2>/dev/null \
            | grep -v -E '(upstream/|release-consistency\.sh|# BAN:keep)' || true)
    if [ -n "$hit" ]; then
      emit "forbidden pattern '$pat' found in $p"
      printf '%s\n' "$hit" | sed 's/^/        /'
    fi
  done
done
[ "$fail" -eq 0 ] && ok "no obsolete references in provisioning/overlay/bin/flow-api/README/docs"

# 2. The vendored upstream must still contain exactly the services the overlay
#    assumes. If upstream drifts, overlay must drift with it (or stack-up fails).
UP=upstream/akvorado-v2026.10.0/docker/docker-compose.yml
OV=overlay/docker-compose.netops.yml
[ -s "$UP" ] || { emit "vendored upstream missing: $UP"; exit 1; }
[ -s "$OV" ] || { emit "overlay missing: $OV"; exit 1; }

REQUIRED_UPSTREAM_SERVICES=(kafka redis clickhouse traefik akvorado-orchestrator akvorado-inlet akvorado-outlet akvorado-console)
for s in "${REQUIRED_UPSTREAM_SERVICES[@]}"; do
  grep -qE "^  $s:$" "$UP" || emit "upstream compose does not declare service: $s"
done

# Overlay must only touch services that exist upstream.
OVERLAY_SERVICES=$(awk '
    /^services:/   { in_services=1; next }
    /^[a-z]/       { in_services=0 }
    in_services && /^  [a-z][a-z0-9-]*:$/ { gsub(":", "", $1); print $1 }' "$OV")
for s in $OVERLAY_SERVICES; do
  grep -qE "^  $s:$" "$UP" || emit "overlay references non-existent upstream service: $s"
done
[ "$fail" -eq 0 ] && ok "upstream/overlay service sets match"

# 3. Images referenced by versions.yml are the canonical ones.
VY=upstream/akvorado-v2026.10.0/docker/versions.yml
for img_pat in \
    'quay.io/akvorado/akvorado:2026\.10\.0' \
    'apache/kafka:4\.' \
    'valkey/valkey:' \
    'clickhouse/clickhouse-server:26\.' \
    'traefik:v3\.' ; do
  grep -qE "$img_pat" "$VY" || emit "versions.yml missing image matching: $img_pat"
done
[ "$fail" -eq 0 ] && ok "versions.yml carries canonical images"

# 4. Every README path reference must have its PARENT directory on disk.
#    (Checking the exact filename is noisy: generated files like
#    overlay/.digests.lock.prev are legitimate dangling references.)
for RM in README.md provisioning/README.md docs/CODEX-NETFLOW-DEPLOY.md; do
  [ -s "$RM" ] || continue
  # Match only tokens that start at a word boundary where the preceding
  # character is NOT '/'. That stops a longer path like
  # ../frontend/modules/FlowSearch/sql/views.sql from being chopped into a
  # bare `sql/views.sql` and then flagged as a missing top-level dir.
  for tok in $(grep -oE '(^|[^/[:alnum:]_.-])(bin|flow-api|overlay|upstream|provisioning|docs)/[A-Za-z0-9._/-]+' "$RM" \
                 | sed -E 's|^[^/[:alnum:]_.-]||' | sort -u); do
    parent=$(dirname "$tok")
    if [ ! -d "$parent" ]; then
      emit "$RM references missing dir: $parent (via $tok)"
    fi
  done
done
[ "$fail" -eq 0 ] && ok "every README path reference has a parent dir on disk"

echo
if [ "$fail" -eq 0 ]; then
  echo "RELEASE CONSISTENCY  PASS"
  exit 0
else
  echo "RELEASE CONSISTENCY  FAIL  ($fail problem(s))"
  exit 1
fi

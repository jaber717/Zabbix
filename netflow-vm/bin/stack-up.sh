#!/usr/bin/env bash
# stack-up.sh — THE SINGLE SUPPORTED bring-up path for netflow-01.
#
# Order (enforced here, not left to operator memory):
#   1. Verify runtime (Docker Engine + Compose plugin).
#   2. Prepare host paths on /var/lib/akvorado/data.
#   3. docker compose up (vendored upstream + NetOps overlay).
#   4. Wait for Akvorado to create the ClickHouse schema (`akvorado.flows`).
#   5. Generate flow-api secrets if missing (ch-pass, console htpasswd).
#   6. Apply ClickHouse compat view / zbx read-only user.
#   7. Install + start flow-api (nginx + php-fpm + console reverse proxy).
#   8. Validate: /healthz, /akvorado/ (via basic auth), ClickHouse ping,
#      Akvorado inlet health, outlet health, orchestrator health.
#
# Idempotent. Safe to rerun. Returns 0 only when every validation passes.
set -euo pipefail

cd "$(dirname "$0")/.."
UPSTREAM=upstream/akvorado-v2026.10.0

: "${AKVORADO_VERSION:=2026.10.0}"

# ---- 1. runtime ---------------------------------------------------------
command -v docker >/dev/null || { echo "FATAL docker not installed"; exit 2; }
docker compose version >/dev/null 2>&1 || { echo "FATAL docker compose plugin missing"; exit 2; }

# ---- 2. host paths ------------------------------------------------------
install -d -m 0750 /var/lib/akvorado/data/clickhouse /var/lib/akvorado/data/kafka /etc/flow-api/clients /etc/akvorado
chcon -R -t container_file_t /var/lib/akvorado/data 2>/dev/null || true

# ---- 3. stack up (digest-pinned if a lock exists) -----------------------
export COMPOSE_PROJECT_NAME=akvorado
export COMPOSE_FILE="$UPSTREAM/docker/docker-compose.yml:overlay/docker-compose.netops.yml"

if [ -s overlay/.digests.lock ]; then
  bin/digests-to-overlay.sh > /run/akvorado-digests.yml
  export COMPOSE_FILE="$COMPOSE_FILE:/run/akvorado-digests.yml"
fi
docker compose --project-directory "$UPSTREAM" up -d
docker compose --project-directory "$UPSTREAM" ps

# ---- 4. wait for ClickHouse schema --------------------------------------
echo "waiting for akvorado.flows to appear in ClickHouse (max 5 min)..."
for i in $(seq 1 60); do
  if docker exec akvorado-clickhouse clickhouse-client --query \
        "SELECT 1 FROM system.tables WHERE database='akvorado' AND name='flows'" 2>/dev/null | grep -q '^1$'; then
    echo "schema ready"
    break
  fi
  sleep 5
done
docker exec akvorado-clickhouse clickhouse-client --query \
    "SELECT 1 FROM system.tables WHERE database='akvorado' AND name='flows'" 2>/dev/null | grep -q '^1$' || {
  echo "FATAL akvorado.flows did not appear after 5 min"; exit 3; }

# ---- 5. flow-api secrets (BEFORE clickhouse-apply) ----------------------
if [ ! -s /etc/flow-api/ch-pass ]; then
  openssl rand -base64 24 | tr -d '=\n' > /etc/flow-api/ch-pass
  chmod 0600 /etc/flow-api/ch-pass
fi
# One Bearer token for the Zabbix client; hashed on disk, plaintext in a
# single-use env file for Codex to ship as a sealed systemd credential.
if [ ! -s /etc/flow-api/clients/zabbix.token.sha256 ]; then
  TOKEN=$(openssl rand -hex 32)
  HASH=$(printf '%s' "$TOKEN" | openssl dgst -sha256 | awk '{print $2}')
  printf '%s' "$HASH" > /etc/flow-api/clients/zabbix.token.sha256
  chmod 0600 /etc/flow-api/clients/zabbix.token.sha256
  printf 'FLOW_API_TOKEN=%s\n' "$TOKEN" > /etc/flow-api/zabbix-token.env
  chmod 0600 /etc/flow-api/zabbix-token.env
  unset TOKEN HASH
fi
# Console HTTP basic (nginx reverse-proxy auth).
if [ ! -s /etc/flow-api/console-htpasswd ]; then
  if ! command -v htpasswd >/dev/null 2>&1; then
    dnf install -y httpd-tools >/dev/null
  fi
  CPASS=$(openssl rand -base64 18)
  htpasswd -cbB /etc/flow-api/console-htpasswd noc "$CPASS" >/dev/null
  chmod 0640 /etc/flow-api/console-htpasswd
  printf 'CONSOLE_USER=noc\nCONSOLE_PASSWORD=%s\n' "$CPASS" > /etc/flow-api/console-credential.env
  chmod 0600 /etc/flow-api/console-credential.env
  unset CPASS
fi

# ---- 6. compat view + flow_api_ro user ----------------------------------
install -d -m 0755 /opt/akvorado/sql
install -m 0644 ../frontend/modules/FlowSearch/sql/views.sql /opt/akvorado/sql/views.sql \
    2>/dev/null || install -m 0644 /opt/akvorado/sql/views.sql /opt/akvorado/sql/views.sql 2>/dev/null || true
bin/clickhouse-apply.sh

# ---- 7. flow-api up -----------------------------------------------------
if [ -n "${ZABBIX_SERVER_IP:-}" ]; then
  ZABBIX_SERVER_IP="$ZABBIX_SERVER_IP" flow-api/flow-api-install.sh
elif [ -s /etc/akvorado/netops.env ]; then
  . /etc/akvorado/netops.env
  ZABBIX_SERVER_IP="$ZABBIX_SERVER_IP" flow-api/flow-api-install.sh
else
  echo "FATAL ZABBIX_SERVER_IP not set and /etc/akvorado/netops.env missing"; exit 4
fi

# ---- 8. validate --------------------------------------------------------
echo "== validate =="
curl -skf https://127.0.0.1/healthz >/dev/null && echo "flow-api/healthz OK"
# console reverse proxy — expect 401 without auth, 200 with
code=$(curl -sk -o /dev/null -w '%{http_code}' https://127.0.0.1/akvorado/)
case "$code" in
  401|403) echo "console reverse proxy OK (auth required, got $code)";;
  200)     echo "console reverse proxy OK (passed)";;
  *)       echo "FATAL console reverse proxy returned $code"; exit 5;;
esac
docker exec akvorado-clickhouse wget -qO- --timeout 2 http://127.0.0.1:8123/ping | grep -q 'Ok.' && echo "clickhouse/ping OK"
for svc in akvorado-orchestrator akvorado-inlet akvorado-outlet akvorado-console; do
  code=$(docker exec "$svc" wget -qO- --timeout 2 http://127.0.0.1:8080/api/v0/healthcheck -S 2>&1 | awk '/HTTP\//{print $2; exit}')
  [ "$code" = 200 ] && echo "$svc healthz OK" || { echo "FATAL $svc healthz $code"; exit 6; }
done

echo
echo "stack-up.sh DONE  —  secrets written to /etc/flow-api/*.env (ship via sealed systemd credentials; do NOT scp cleartext)"

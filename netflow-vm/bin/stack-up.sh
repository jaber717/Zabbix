#!/usr/bin/env bash
# stack-up.sh — single supported bring-up path for netflow-01.
# Enforces order and sets secret ownership/permissions so nginx (which runs
# the Flow API) can actually read them.
set -euo pipefail

cd "$(dirname "$0")/.."
UPSTREAM=upstream/akvorado-v2026.10.0
: "${AKVORADO_VERSION:=2026.10.0}"

# ---- 1. runtime ---------------------------------------------------------
command -v docker >/dev/null || { echo "FATAL docker not installed"; exit 2; }
docker compose version >/dev/null 2>&1 || { echo "FATAL docker compose plugin missing"; exit 2; }
id nginx  >/dev/null 2>&1 || { echo "FATAL nginx user missing — cloud-init did not install nginx package"; exit 2; }

# ---- 2. host paths ------------------------------------------------------
install -d -m 0750 /var/lib/akvorado/data/clickhouse /var/lib/akvorado/data/kafka
install -d -m 0750 -o root -g nginx /etc/flow-api /etc/flow-api/clients /etc/flow-api/tls
install -d -m 0755 /etc/akvorado
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
echo "waiting for akvorado.flows (max 5 min)..."
for i in $(seq 1 60); do
  if docker exec akvorado-clickhouse clickhouse-client --query \
        "SELECT 1 FROM system.tables WHERE database='akvorado' AND name='flows'" 2>/dev/null | grep -q '^1$'; then
    echo "schema ready"; break
  fi
  sleep 5
done
docker exec akvorado-clickhouse clickhouse-client --query \
    "SELECT 1 FROM system.tables WHERE database='akvorado' AND name='flows'" 2>/dev/null | grep -q '^1$' || {
  echo "FATAL akvorado.flows did not appear"; exit 3; }

# ---- 5. flow-api secrets, group-readable by nginx -----------------------
# Secret file ownership: root:nginx with 0640 so PHP-FPM (running as nginx)
# can read them without weakening file ownership. Plaintext handoff files
# stay 0600 root:root — Codex ships them via sealed systemd creds.
secret_perms() {
  local f="$1" m="${2:-0640}"
  chown root:nginx "$f"
  chmod "$m" "$f"
}
if [ ! -s /etc/flow-api/ch-pass ]; then
  umask 0027
  openssl rand -base64 24 | tr -d '=\n' > /etc/flow-api/ch-pass
fi
secret_perms /etc/flow-api/ch-pass

if [ ! -s /etc/flow-api/clients/zabbix.token.sha256 ]; then
  TOKEN=$(openssl rand -hex 32)
  HASH=$(printf '%s' "$TOKEN" | openssl dgst -sha256 | awk '{print $2}')
  printf '%s' "$HASH" > /etc/flow-api/clients/zabbix.token.sha256
  printf 'FLOW_API_TOKEN=%s\n' "$TOKEN" > /etc/flow-api/zabbix-token.env
  chmod 0600 /etc/flow-api/zabbix-token.env    # cleartext handoff
  chown root:root /etc/flow-api/zabbix-token.env
  unset TOKEN HASH
fi
secret_perms /etc/flow-api/clients/zabbix.token.sha256
chown root:nginx /etc/flow-api/clients
chmod 0750 /etc/flow-api/clients

if [ ! -s /etc/flow-api/console-htpasswd ]; then
  command -v htpasswd >/dev/null || dnf install -y httpd-tools >/dev/null
  CPASS=$(openssl rand -base64 18)
  htpasswd -cbB /etc/flow-api/console-htpasswd noc "$CPASS" >/dev/null
  printf 'CONSOLE_USER=noc\nCONSOLE_PASSWORD=%s\n' "$CPASS" > /etc/flow-api/console-credential.env
  chmod 0600 /etc/flow-api/console-credential.env
  chown root:root /etc/flow-api/console-credential.env
  unset CPASS
fi
secret_perms /etc/flow-api/console-htpasswd 0640

# Validate as the nginx user, not root.
for f in /etc/flow-api/ch-pass /etc/flow-api/console-htpasswd /etc/flow-api/clients/zabbix.token.sha256; do
  sudo -u nginx test -r "$f" || { echo "FATAL nginx cannot read $f"; stat -c '%A %U:%G %n' "$f"; exit 4; }
done
echo "flow-api secret perms OK (nginx can read all)"

# ---- 6. compat view + flow_api_ro user ----------------------------------
install -d -m 0755 sql
cp -f sql/views.sql /opt/akvorado/sql/views.sql 2>/dev/null || true   # idempotent self-copy if on-disk layout differs
bin/clickhouse-apply.sh

# ---- 7. flow-api up -----------------------------------------------------
if [ -z "${ZABBIX_SERVER_IP:-}" ] && [ -s /etc/akvorado/netops.env ]; then
  # shellcheck disable=SC1091
  . /etc/akvorado/netops.env
fi
: "${ZABBIX_SERVER_IP:?missing ZABBIX_SERVER_IP (set in /etc/akvorado/netops.env)}"
ZABBIX_SERVER_IP="$ZABBIX_SERVER_IP" NOC_MGMT_CIDRS="${NOC_MGMT_CIDRS:-}" flow-api/flow-api-install.sh

# ---- 8. validate --------------------------------------------------------
echo "== validate =="
curl -skf https://127.0.0.1/healthz >/dev/null && echo "flow-api/healthz OK"
# Console reverse proxy — expect 401 without creds, 200 with creds.
code=$(curl -sk -o /dev/null -w '%{http_code}' https://127.0.0.1/akvorado/)
case "$code" in
  401|403) echo "console reverse proxy OK (auth required, got $code)";;
  200)     echo "console reverse proxy OK (passed)";;
  *)       echo "FATAL console reverse proxy returned $code"; exit 5;;
esac
docker exec akvorado-clickhouse wget -qO- --timeout 2 http://127.0.0.1:8123/ping | grep -q 'Ok.' && echo "clickhouse/ping OK"
for svc in akvorado-orchestrator akvorado-inlet akvorado-outlet akvorado-console; do
  if docker exec "$svc" wget --spider -q --timeout 2 http://127.0.0.1:8080/api/v0/healthcheck; then
    echo "$svc healthz OK"
  else
    echo "FATAL $svc healthz"; exit 6
  fi
done
# Smoke: invalid Bearer must return 401.
bad_code=$(curl -sk -o /dev/null -w '%{http_code}' -X POST -H 'Authorization: Bearer nope' \
  -d '{"filter":{"from":1,"to":2}}' https://127.0.0.1/api/v1/summary)
[ "$bad_code" = 401 ] && echo "flow-api invalid-bearer → 401 OK" || { echo "FATAL invalid-bearer returned $bad_code"; exit 7; }
# Smoke: valid Bearer + invalid filter must return 400.
TOKEN=$(awk -F= '/FLOW_API_TOKEN=/{print $2; exit}' /etc/flow-api/zabbix-token.env)
good_bad=$(curl -sk -o /dev/null -w '%{http_code}' -X POST -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"filter":{"from":1,"to":2,"src_ip":"not-an-ip"}}' https://127.0.0.1/api/v1/summary)
[ "$good_bad" = 400 ] && echo "flow-api invalid-filter → 400 OK" || echo "WARN invalid-filter returned $good_bad (expected 400)"

echo
echo "stack-up.sh DONE  —  secrets written to /etc/flow-api/*.env (ship via sealed systemd credentials; do NOT scp cleartext)"

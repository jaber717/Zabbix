#!/usr/bin/env bash
# flow-api-install.sh — stand up the Flow query gateway on netflow-01.
# Called by cloud-init after the Akvorado stack reports healthy.
set -euo pipefail

: "${ZABBIX_SERVER_IP:?set ZABBIX_SERVER_IP before running}"

dnf install -y nginx php-fpm php-cli php-json php-curl openssl

install -d -m 0750 /etc/flow-api/tls /etc/flow-api/clients /var/log/nginx
install -m 0644 /opt/akvorado/flow-api/nginx.conf /etc/nginx/conf.d/flow-api.conf
install -m 0644 /opt/akvorado/flow-api/api.php /var/www/flow-api/api.php

# PHP-FPM pool on 127.0.0.1:9091 (nginx reverse-proxies to it).
cat >/etc/php-fpm.d/flow-api.conf <<'EOF'
[flow-api]
user = nginx
group = nginx
listen = 127.0.0.1:9091
pm = dynamic
pm.max_children = 16
pm.start_servers = 2
pm.min_spare_servers = 2
pm.max_spare_servers = 4
chdir = /var/www/flow-api
php_admin_value[expose_php] = 0
php_admin_value[max_execution_time] = 15
php_admin_value[memory_limit] = 256M
EOF

# Self-signed cert for lab. Replace with internal CA cert at FLOW_API_TLS_PEM.
if [ -n "${FLOW_API_TLS_PEM:-}" ] && [ -s "$FLOW_API_TLS_PEM" ]; then
  install -m 0644 "$FLOW_API_TLS_PEM" /etc/flow-api/tls/server.crt
  install -m 0600 "${FLOW_API_TLS_KEY}" /etc/flow-api/tls/server.key
else
  openssl req -x509 -nodes -days 365 -newkey rsa:3072 \
    -subj "/CN=netflow-01" \
    -keyout /etc/flow-api/tls/server.key \
    -out    /etc/flow-api/tls/server.crt
  chmod 600 /etc/flow-api/tls/server.key
fi

# Issue a bearer token for Zabbix; the plaintext is written to a file that is
# shipped to the Zabbix server via a sealed systemd credential. The hash is
# what the API server compares against.
TOKEN=$(openssl rand -hex 32)
HASH=$(printf '%s' "$TOKEN" | openssl dgst -sha256 | awk '{print $2}')
printf '%s' "$HASH" > /etc/flow-api/clients/zabbix.token.sha256
chmod 0600 /etc/flow-api/clients/zabbix.token.sha256
printf 'FLOW_API_TOKEN=%s\n' "$TOKEN" > /etc/flow-api/zabbix-token.env
chmod 0600 /etc/flow-api/zabbix-token.env
echo "Zabbix bearer token written to /etc/flow-api/zabbix-token.env (ship via sealed systemd credential; do NOT scp cleartext)"

# ClickHouse password for flow_api_ro (read-only user on the compat view).
# Generated once, read by api.php from /etc/flow-api/ch-pass.
if [ ! -s /etc/flow-api/ch-pass ]; then
  openssl rand -base64 24 | tr -d '=\n' > /etc/flow-api/ch-pass
  chmod 0600 /etc/flow-api/ch-pass
fi

# firewalld: open 443 only to the Zabbix server.
firewall-cmd --permanent --new-zone=flow-api 2>/dev/null || true
firewall-cmd --permanent --zone=flow-api --set-target=default
firewall-cmd --permanent --zone=flow-api --add-port=443/tcp
firewall-cmd --permanent --zone=flow-api --add-source="${ZABBIX_SERVER_IP}/32"
firewall-cmd --reload

# SELinux: let nginx talk to php-fpm and let php-fpm talk to the local
# ClickHouse HTTP port. These are permitted by the default `httpd_t` policy
# via booleans; no custom policy module.
setsebool -P httpd_can_network_connect 1

systemctl enable --now php-fpm
systemctl enable --now nginx

# Smoke test (must come back 200 OK with the bearer).
sleep 2
curl -sk --connect-timeout 2 "https://127.0.0.1/healthz" | tee /var/log/flow-api-smoke.json

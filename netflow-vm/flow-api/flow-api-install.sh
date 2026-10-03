#!/usr/bin/env bash
# flow-api-install.sh — install/start the Flow API gateway (nginx + PHP-FPM
# over FastCGI + Akvorado console reverse proxy). Idempotent. Called by
# bin/stack-up.sh AFTER secrets are provisioned on disk with correct perms.
set -euo pipefail

: "${ZABBIX_SERVER_IP:?set ZABBIX_SERVER_IP}"

# Packages installed by cloud-init; this is defensive-idempotent.
dnf install -y nginx php-fpm php-cli php-json php-curl openssl httpd-tools

install -d -m 0755 /var/www/flow-api
install -m 0644 /opt/akvorado/flow-api/nginx.conf /etc/nginx/conf.d/flow-api.conf
install -m 0644 /opt/akvorado/flow-api/api.php    /var/www/flow-api/api.php
chown nginx:nginx /var/www/flow-api/api.php

# PHP-FPM pool on 127.0.0.1:9091 (FastCGI, not HTTP).
cat >/etc/php-fpm.d/flow-api.conf <<'EOF'
[flow-api]
user = nginx
group = nginx
listen = 127.0.0.1:9091
listen.allowed_clients = 127.0.0.1
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

# TLS: operator-supplied cert overrides self-signed.
if [ -n "${FLOW_API_TLS_PEM:-}" ] && [ -s "$FLOW_API_TLS_PEM" ]; then
  install -m 0644 "$FLOW_API_TLS_PEM" /etc/flow-api/tls/server.crt
  install -m 0600 "${FLOW_API_TLS_KEY}" /etc/flow-api/tls/server.key
elif [ ! -s /etc/flow-api/tls/server.crt ]; then
  openssl req -x509 -nodes -days 365 -newkey rsa:3072 \
    -subj "/CN=$(hostname -f 2>/dev/null || hostname)" \
    -keyout /etc/flow-api/tls/server.key \
    -out    /etc/flow-api/tls/server.crt
  chmod 600 /etc/flow-api/tls/server.key
fi
chown root:nginx /etc/flow-api/tls/server.key
chmod 0640 /etc/flow-api/tls/server.key

# Sanity-check nginx config BEFORE restart. Fail hard on syntax error.
nginx -t

systemctl enable --now php-fpm
systemctl restart nginx
systemctl enable nginx

# Smoke test (nginx self, FastCGI roundtrip).
code=$(curl -sk --connect-timeout 2 -o /tmp/healthz.body -w '%{http_code}' https://127.0.0.1/healthz)
echo "flow-api self-smoke https://127.0.0.1/healthz -> HTTP $code"
cat /tmp/healthz.body; echo
[ "$code" = 200 ] || { echo "FATAL /healthz did not return 200"; exit 1; }

#!/usr/bin/env bash
# flow-api-install.sh — install/start the Flow API gateway (nginx + PHP-FPM
# + Akvorado console reverse proxy). Idempotent. Called by bin/stack-up.sh
# AFTER the stack is up and flow-api secrets are in /etc/flow-api/*.
set -euo pipefail

: "${ZABBIX_SERVER_IP:?set ZABBIX_SERVER_IP}"

dnf install -y nginx php-fpm php-cli php-json php-curl openssl httpd-tools

install -d -m 0750 /etc/flow-api/tls /etc/flow-api/clients /var/log/nginx /var/www/flow-api
install -m 0644 /opt/akvorado/flow-api/nginx.conf /etc/nginx/conf.d/flow-api.conf
install -m 0644 /opt/akvorado/flow-api/api.php /var/www/flow-api/api.php

# PHP-FPM pool on 127.0.0.1:9091.
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

# firewalld: port 443 is open to the Zabbix server AND the NOC mgmt CIDRs
# (the latter needed because operators reach the Akvorado console via the
# same nginx under /akvorado/). The exporter zone and SSH stay untouched.
firewall-cmd --permanent --new-zone=flow-api 2>/dev/null || true
firewall-cmd --permanent --zone=flow-api --set-target=default
firewall-cmd --permanent --zone=flow-api --add-port=443/tcp
firewall-cmd --permanent --zone=flow-api --add-source="${ZABBIX_SERVER_IP}/32"
if [ -n "${NOC_MGMT_CIDRS:-}" ]; then
  IFS=',' read -r -a arr <<< "$NOC_MGMT_CIDRS"
  for c in "${arr[@]}"; do
    firewall-cmd --permanent --zone=flow-api --add-source="$c"
  done
fi
firewall-cmd --reload

systemctl enable --now php-fpm
systemctl restart nginx
systemctl enable nginx

# Smoke test (nginx self).
curl -sk --connect-timeout 2 https://127.0.0.1/healthz | tee /var/log/flow-api-smoke.json
echo

#!/usr/bin/env bash
# runtime-preflight.sh — executable checks that complement release-consistency.
# Runs OFF the target VM (no Docker required). Validates that the shipped
# tree is actually a deployable artifact.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail=0
emit() { echo "FAIL  $*"; fail=$((fail+1)); }
ok()   { echo "ok    $*"; }

# 1. SQL payload ships inside netflow-vm.
if [ -s sql/views.sql ]; then
  ok "sql/views.sql ships with the tree"
  grep -q 'CREATE OR REPLACE VIEW netops.flow_v1' sql/views.sql \
    || emit "sql/views.sql missing CREATE OR REPLACE VIEW netops.flow_v1"
  grep -q 'CREATE USER IF NOT EXISTS flow_api_ro' sql/views.sql \
    || emit "sql/views.sql missing CREATE USER IF NOT EXISTS flow_api_ro"
else
  emit "sql/views.sql missing — would crash clickhouse-apply.sh"
fi
# Drift check: Zabbix module's SQL must match ours bit for bit.
if [ -s ../frontend/modules/FlowSearch/sql/views.sql ] && [ -s sql/views.sql ]; then
  if ! diff -q sql/views.sql ../frontend/modules/FlowSearch/sql/views.sql >/dev/null; then
    emit "SQL drift: netflow-vm/sql/views.sql differs from frontend/modules/FlowSearch/sql/views.sql"
  else
    ok "SQL copies are bit-identical"
  fi
fi

# 2. cloud-init does not call files that don't exist on first boot.
#    First-boot cloud-init runs BEFORE the netflow-vm tree is rsynced in.
# Ignore comment lines (prose that explains what we do NOT do).
if grep -vE '^\s*#' provisioning/cloud-init.user-data.yaml | grep -qE '/opt/akvorado/'; then
  emit "cloud-init.user-data.yaml references /opt/akvorado/* — races the rsync"
else
  ok "cloud-init does not reference /opt/akvorado/* at first boot"
fi

# 3. qemu-guest-agent is packaged.
grep -q 'qemu-guest-agent' provisioning/cloud-init.user-data.yaml \
  && ok "cloud-init installs qemu-guest-agent" \
  || emit "cloud-init missing qemu-guest-agent"

# 4. Both admin and bootstrap keys are injected at first boot.
grep -q '\${NETOPS_ADMIN_PUBKEY}' provisioning/cloud-init.user-data.yaml \
  && grep -q '\${BOOT_PUBKEY}' provisioning/cloud-init.user-data.yaml \
  && ok "cloud-init injects admin + ephemeral bootstrap keys" \
  || emit "cloud-init missing admin or bootstrap key injection"

# 5. Proxmox provisioning uses --ssh-private-key-file or generates ephemeral.
grep -q 'ssh-keygen -t ed25519' provisioning/create-netflow-proxmox.sh \
  && grep -q 'ssh-private-key-file' provisioning/create-netflow-proxmox.sh \
  && ok "create-netflow-proxmox.sh supports private key AND generates ephemeral" \
  || emit "create-netflow-proxmox.sh missing deterministic SSH bootstrap"

# 6. Proxmox import parses the actual disk name instead of guessing.
grep -q 'parse.*unused' provisioning/create-netflow-proxmox.sh \
  || grep -q 'awk.*unused' provisioning/create-netflow-proxmox.sh \
  || emit "create-netflow-proxmox.sh does not parse qm config for imported disk"
grep -q 'IMPORTED_DISK' provisioning/create-netflow-proxmox.sh \
  && ok "create-netflow-proxmox.sh parses imported disk name" \
  || emit "create-netflow-proxmox.sh hardcodes imported disk name"

# 7. nginx uses FastCGI (not HTTP proxy) for api.php endpoints.
grep -q 'fastcgi_pass 127.0.0.1:9091' flow-api/nginx.conf \
  && ok "nginx /healthz + /api/v1/* use fastcgi_pass to PHP-FPM" \
  || emit "nginx not using fastcgi_pass for PHP-FPM"
grep -q 'proxy_pass http://127.0.0.1:9091' flow-api/nginx.conf \
  && emit "nginx still has HTTP proxy to PHP-FPM — PHP-FPM speaks FastCGI, not HTTP"

# 8. nginx config syntax (if nginx is on the controller; usually not — skipped silently).
if command -v nginx >/dev/null 2>&1; then
  nginx -t -c flow-api/nginx.conf >/dev/null 2>&1 \
    && ok "nginx -t syntax OK" || emit "nginx -t rejected flow-api/nginx.conf"
fi

# 9. Secret ownership plan: stack-up sets root:nginx 0640, not root:root 0600.
grep -q 'chown root:nginx /etc/flow-api/ch-pass' bin/stack-up.sh && \
grep -q 'chmod .* /etc/flow-api/ch-pass'          bin/stack-up.sh || true
if grep -q 'secret_perms' bin/stack-up.sh && grep -q 'sudo -u nginx test -r' bin/stack-up.sh; then
  ok "stack-up.sh fixes secret ownership and validates AS nginx"
else
  emit "stack-up.sh does not validate secret readability from nginx"
fi

# 10. Firewall exposes all three collector ports from EXPORTER_CIDRS only.
#     Match either an explicit `add-port=P` or P appearing in a loop list.
for p in 2055/udp 4739/udp 6343/udp; do
  if grep -qE "(add-port=${p}|\\b${p}\\b)" provisioning/firewalld-apply.sh; then
    :  # found
  else
    emit "firewalld-apply.sh does not open $p"
  fi
done
grep -q 'zone=flow-exporters --add-source' provisioning/firewalld-apply.sh \
  && ok "firewalld restricts collector ports to EXPORTER_CIDRS" \
  || emit "firewalld-apply.sh exposes collector ports broadly"

grep -q 'zone=zabbix --add-source' provisioning/firewalld-apply.sh \
  && ok "firewalld scopes zabbix zone to the server IP during bootstrap" \
  || emit "firewalld-apply.sh leaves zabbix source unscoped"

# 11. Overlay removes upstream's console-auth demo middleware.
grep -q 'console-auth' overlay/docker-compose.netops.yml \
  && grep -q 'NO .middlewares=console-auth' overlay/docker-compose.netops.yml \
  && ok "overlay removes upstream console-auth demo middleware" \
  || emit "overlay still carries upstream console-auth demo middleware"

# 12. stack-up dependencies all present inside the shipped tree.
for req in bin/clickhouse-apply.sh bin/digests-to-overlay.sh bin/pin-digests.sh \
           flow-api/flow-api-install.sh flow-api/nginx.conf flow-api/api.php \
           overlay/docker-compose.netops.yml overlay/clickhouse/users.d/zbx-flow-ro-profile.xml \
           upstream/akvorado-v2026.10.0/docker/docker-compose.yml \
           upstream/akvorado-v2026.10.0/docker/versions.yml \
           sql/views.sql; do
  [ -s "$req" ] || emit "stack-up depends on missing file: $req"
done
[ "$fail" -eq 0 ] && ok "every stack-up dependency exists inside netflow-vm/"

echo
if [ "$fail" -eq 0 ]; then
  echo "RUNTIME PREFLIGHT  PASS"
  exit 0
else
  echo "RUNTIME PREFLIGHT  FAIL  ($fail problem(s))"
  exit 1
fi

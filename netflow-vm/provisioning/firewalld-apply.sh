#!/usr/bin/env bash
# Deploy firewalld zones + rich rules for the NetFlow VM.
# Called by cloud-init with: $1 = exporter CIDR list (comma-sep), $2 = NOC mgmt CIDR list.
# SELinux stays Enforcing; firewalld stays active. No disables, ever.
set -euo pipefail

EXPORTER_CIDRS="${1:-}"
NOC_CIDRS="${2:-}"
if [ -z "$EXPORTER_CIDRS" ] || [ -z "$NOC_CIDRS" ]; then
  echo "usage: $0 <exporter-cidrs,comma-sep> <noc-mgmt-cidrs,comma-sep>"; exit 2
fi

# Public zone: drop everything by default.
firewall-cmd --permanent --set-default-zone=public
firewall-cmd --permanent --zone=public --set-target=DROP

# flow-exporters zone: UDP/2055 from exporter CIDRs only.
firewall-cmd --permanent --new-zone=flow-exporters 2>/dev/null || true
firewall-cmd --permanent --zone=flow-exporters --set-target=default
firewall-cmd --permanent --zone=flow-exporters --add-port=2055/udp
IFS=',' read -r -a CIDRS <<< "$EXPORTER_CIDRS"
for c in "${CIDRS[@]}"; do
  firewall-cmd --permanent --zone=flow-exporters --add-source="$c"
done

# noc-mgmt zone: TCP/443 (nginx → akvorado console) and TCP/22 for admin, from NOC CIDRs only.
firewall-cmd --permanent --new-zone=noc-mgmt 2>/dev/null || true
firewall-cmd --permanent --zone=noc-mgmt --set-target=default
firewall-cmd --permanent --zone=noc-mgmt --add-service=ssh
firewall-cmd --permanent --zone=noc-mgmt --add-port=443/tcp
IFS=',' read -r -a NC <<< "$NOC_CIDRS"
for c in "${NC[@]}"; do
  firewall-cmd --permanent --zone=noc-mgmt --add-source="$c"
done

# Zabbix-server zone: TCP/10050 (agent) from the Zabbix server IP only — set via drop-in by Codex.
firewall-cmd --permanent --new-zone=zabbix 2>/dev/null || true
firewall-cmd --permanent --zone=zabbix --set-target=default
firewall-cmd --permanent --zone=zabbix --add-port=10050/tcp
# Codex: add --add-source=<zabbix-server-ip>/32 at onboarding time.

firewall-cmd --reload
firewall-cmd --list-all-zones | head -80

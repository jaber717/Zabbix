#!/usr/bin/env bash
# firewalld-apply.sh — zones + sources for netflow-01.
# Called by create-netflow-proxmox.sh AFTER the netflow-vm tree is on disk.
# Opens the three Akvorado inlet collector ports (2055/4739/6343 UDP) from
# EXPORTER_CIDRS only, 443/tcp from NOC_CIDRS + Zabbix server, SSH from NOC
# only. SELinux stays Enforcing.
set -euo pipefail

EXPORTER_CIDRS="${1:-}"
NOC_CIDRS="${2:-}"
ZABBIX_SERVER_IP="${3:-}"
[ -n "$EXPORTER_CIDRS" ] && [ -n "$NOC_CIDRS" ] && [ -n "$ZABBIX_SERVER_IP" ] || {
  echo "usage: $0 <exporter-cidrs,csv> <noc-mgmt-cidrs,csv> <zabbix-server-ip>"; exit 2
}

firewall-cmd --permanent --set-default-zone=public
firewall-cmd --permanent --zone=public --set-target=DROP

# flow-exporters: all three Akvorado collector ports, exporter CIDRs only.
firewall-cmd --permanent --new-zone=flow-exporters 2>/dev/null || true
firewall-cmd --permanent --zone=flow-exporters --set-target=default
for port in 2055/udp 4739/udp 6343/udp; do
  firewall-cmd --permanent --zone=flow-exporters --add-port="$port"
done
IFS=',' read -r -a CIDRS <<< "$EXPORTER_CIDRS"
for c in "${CIDRS[@]}"; do
  firewall-cmd --permanent --zone=flow-exporters --add-source="$c"
done

# noc-mgmt: SSH + the Flow API gateway's /akvorado/ console path.
firewall-cmd --permanent --new-zone=noc-mgmt 2>/dev/null || true
firewall-cmd --permanent --zone=noc-mgmt --set-target=default
firewall-cmd --permanent --zone=noc-mgmt --add-service=ssh
firewall-cmd --permanent --zone=noc-mgmt --add-port=443/tcp
IFS=',' read -r -a NC <<< "$NOC_CIDRS"
for c in "${NC[@]}"; do
  firewall-cmd --permanent --zone=noc-mgmt --add-source="$c"
done

# zabbix: 10050 (zabbix-agent2) + 443/tcp (Flow API) from the single Zabbix server IP.
# Applied here during bootstrap, not left as a TODO.
firewall-cmd --permanent --new-zone=zabbix 2>/dev/null || true
firewall-cmd --permanent --zone=zabbix --set-target=default
firewall-cmd --permanent --zone=zabbix --add-port=10050/tcp
firewall-cmd --permanent --zone=zabbix --add-port=443/tcp
firewall-cmd --permanent --zone=zabbix --add-source="${ZABBIX_SERVER_IP}/32"

firewall-cmd --reload
firewall-cmd --list-all-zones | head -120

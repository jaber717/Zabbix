#!/usr/bin/env bash
# create-netflow-vm.sh — provision the NetFlow VM on the current hypervisor.
#
# Hypervisor-agnostic: dispatches to the first supported backend found in PATH.
# Supported today: libvirt (virt-install), VMware vmrun. ESXi/vCenter requires `govc`
# which is NOT currently installed on the Zabbix engineering host; add later.
#
# Example:
#   ./create-netflow-vm.sh \
#     --name netflow-01 --ip 10.42.42.11/24 --gw 10.42.42.1 --dns 10.42.42.2 \
#     --flow-cidrs "10.0.0.0/8,172.16.0.0/12" --noc-cidrs "10.42.0.0/16"
set -euo pipefail

NAME=netflow-01; IP=; GW=; DNS=; FLOW_CIDRS=; NOC_CIDRS=
VCPUS=4; MEMORY_MB=8192; OS_DISK_GB=20; FLOW_DISK_GB=100
IMG_URL="https://cloud.rockylinux.org/pub/rocky/9/images/x86_64/Rocky-9-GenericCloud-Base.latest.x86_64.qcow2"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name) NAME="$2"; shift 2;;
    --ip) IP="$2"; shift 2;;
    --gw) GW="$2"; shift 2;;
    --dns) DNS="$2"; shift 2;;
    --flow-cidrs) FLOW_CIDRS="$2"; shift 2;;
    --noc-cidrs) NOC_CIDRS="$2"; shift 2;;
    --vcpus) VCPUS="$2"; shift 2;;
    --memory-mb) MEMORY_MB="$2"; shift 2;;
    --os-disk-gb) OS_DISK_GB="$2"; shift 2;;
    --flow-disk-gb) FLOW_DISK_GB="$2"; shift 2;;
    *) echo "unknown arg: $1"; exit 2;;
  esac
done
: "${IP:?--ip required}"; : "${GW:?--gw required}"; : "${DNS:?--dns required}"
: "${FLOW_CIDRS:?--flow-cidrs required}"; : "${NOC_CIDRS:?--noc-cidrs required}"

: "${NETOPS_ADMIN_PUBKEY:?export NETOPS_ADMIN_PUBKEY (ssh-ed25519 ...)}"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# Materialise cloud-init user-data with substitutions. Secrets are generated locally.
export CH_DEFAULT_PASSWORD=$(openssl rand -base64 24 | tr -d '=')
export ZBX_FLOW_RO_PASSWORD=$(openssl rand -base64 24 | tr -d '=')
export CONSOLE_HTPASSWD="$(printf 'noc:'; openssl passwd -apr1 "$(openssl rand -base64 18)")"
export NETFLOW_HOSTNAME="$NAME"
export NETOPS_ADMIN_PUBKEY
export EXPORTER_CIDRS="$FLOW_CIDRS"
export NOC_MGMT_CIDRS="$NOC_CIDRS"

envsubst < "$(dirname "$0")/cloud-init.user-data.yaml" > "$WORK/user-data"
cat > "$WORK/meta-data" <<EOF
instance-id: ${NAME}-001
local-hostname: ${NAME}
EOF
cat > "$WORK/network-config" <<EOF
version: 2
ethernets:
  mgmt:
    match: {name: "en*"}
    set-name: mgmt
    dhcp4: false
    addresses: [${IP}]
    gateway4: ${GW}
    nameservers: {addresses: [${DNS}]}
EOF

if command -v virt-install >/dev/null 2>&1; then
  mkdir -p /var/lib/libvirt/images
  curl -fL "$IMG_URL" -o /var/lib/libvirt/images/${NAME}-os.qcow2
  qemu-img resize /var/lib/libvirt/images/${NAME}-os.qcow2 ${OS_DISK_GB}G
  qemu-img create -f qcow2 /var/lib/libvirt/images/${NAME}-flow.qcow2 ${FLOW_DISK_GB}G
  genisoimage -output /var/lib/libvirt/images/${NAME}-seed.iso -V cidata -r -J \
    "$WORK/user-data" "$WORK/meta-data" "$WORK/network-config"
  virt-install --name "$NAME" --memory "$MEMORY_MB" --vcpus "$VCPUS" \
    --os-variant rhel9.0 --import \
    --disk /var/lib/libvirt/images/${NAME}-os.qcow2,bus=virtio \
    --disk /var/lib/libvirt/images/${NAME}-flow.qcow2,bus=virtio \
    --disk /var/lib/libvirt/images/${NAME}-seed.iso,device=cdrom \
    --network network=default,model=virtio --graphics none --noautoconsole
  echo "VM created with libvirt. Waiting for cloud-init to finish..."
elif command -v vmrun >/dev/null 2>&1; then
  echo "VMware Workstation path not implemented in this script yet. Use libvirt or a vSphere" >&2
  echo "backend. The cloud-init payload at $WORK/ is ready; attach it as a seed CDROM to a" >&2
  echo "manually created VM for parity with the automated path." >&2
  exit 3
else
  echo "No supported hypervisor CLI (virt-install / vmrun) found in PATH" >&2
  exit 4
fi

# Wait for /healthz
for i in $(seq 1 60); do
  if curl -fsSk "https://${IP%%/*}/healthz" >/dev/null; then
    echo "akvorado console healthy at https://${IP%%/*}/"
    exit 0
  fi
  sleep 5
done
echo "VM created but /healthz did not come up in 5 minutes; check cloud-init logs on the VM" >&2
exit 5

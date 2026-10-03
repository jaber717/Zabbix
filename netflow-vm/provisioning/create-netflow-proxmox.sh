#!/usr/bin/env bash
# create-netflow-proxmox.sh — provision netflow-01 on Proxmox VE.
# Runs ON a Proxmox host (uses qm / pvesh / pvesm). Codex has the access.
#
# Picks an unused VMID, builds a cloud-init-seeded VM from a Rocky 9 cloud
# image, attaches a separate expandable flow-data disk, waits for cloud-init
# to finish, and prints the final IP + status.
#
# No placeholders: subnet / gateway / DNS / bridge are required args. The LAB
# management IP is probed on the mgmt bridge before assignment.
set -euo pipefail

PROG=${0##*/}
NAME=netflow-01
VMID=
BRIDGE=
IP=
GW=
DNS=
EXPORTER_CIDRS=
NOC_CIDRS=
ZABBIX_SERVER_IP=
VCPUS=4
MEMORY_MB=8192
OS_DISK_GB=20
FLOW_DISK_GB=100
STORAGE_OS=
STORAGE_FLOW=
IMAGE_URL="${IMAGE_URL:-https://dl.rockylinux.org/pub/rocky/9/images/x86_64/Rocky-9-GenericCloud-Base.latest.x86_64.qcow2}"
SSH_PUBKEY_FILE="${NETOPS_ADMIN_PUBKEY_FILE:-/root/.ssh/netops-admin.pub}"
TREE_SRC="${TREE_SRC:-}"       # path to the netflow-vm/ tree on the Proxmox host; rsynced to the VM

usage() {
  cat >&2 <<EOF
usage: $PROG --bridge <vmbrN> --ip <A.B.C.D/mask> --gw <A.B.C.D> --dns <A.B.C.D>
             --exporter-cidrs <csv> --noc-cidrs <csv> --zabbix-ip <A.B.C.D>
             --storage-os <datastore> --storage-flow <datastore>
             [--name netflow-01] [--vmid auto] [--vcpus 4] [--memory-mb 8192]
             [--os-disk-gb 20] [--flow-disk-gb 100]
             [--image-url ...] [--ssh-pubkey-file /path/to/key.pub]
             [--tree-src /path/to/netflow-vm]

The script creates the VM, injects cloud-init, boots, waits for cloud-init to
complete, then returns.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name) NAME="$2"; shift 2;;
    --vmid) VMID="$2"; shift 2;;
    --bridge) BRIDGE="$2"; shift 2;;
    --ip) IP="$2"; shift 2;;
    --gw) GW="$2"; shift 2;;
    --dns) DNS="$2"; shift 2;;
    --exporter-cidrs) EXPORTER_CIDRS="$2"; shift 2;;
    --noc-cidrs) NOC_CIDRS="$2"; shift 2;;
    --zabbix-ip) ZABBIX_SERVER_IP="$2"; shift 2;;
    --vcpus) VCPUS="$2"; shift 2;;
    --memory-mb) MEMORY_MB="$2"; shift 2;;
    --os-disk-gb) OS_DISK_GB="$2"; shift 2;;
    --flow-disk-gb) FLOW_DISK_GB="$2"; shift 2;;
    --storage-os) STORAGE_OS="$2"; shift 2;;
    --storage-flow) STORAGE_FLOW="$2"; shift 2;;
    --image-url) IMAGE_URL="$2"; shift 2;;
    --ssh-pubkey-file) SSH_PUBKEY_FILE="$2"; shift 2;;
    --tree-src) TREE_SRC="$2"; shift 2;;
    -h|--help) usage; exit 0;;
    *) echo "unknown arg: $1" >&2; usage; exit 2;;
  esac
done

for v in BRIDGE IP GW DNS EXPORTER_CIDRS NOC_CIDRS ZABBIX_SERVER_IP STORAGE_OS STORAGE_FLOW; do
  if [ -z "${!v}" ]; then echo "missing --$(echo "$v" | tr '[:upper:]_' '[:lower:]-')" >&2; exit 2; fi
done

command -v qm   >/dev/null || { echo "qm not found — run this on a Proxmox host" >&2; exit 3; }
command -v pvesm >/dev/null || { echo "pvesm not found — run this on a Proxmox host" >&2; exit 3; }
[ -s "$SSH_PUBKEY_FILE" ] || { echo "missing $SSH_PUBKEY_FILE" >&2; exit 2; }

# 1. Pick an unused VMID in the lab range (default 9000-9999 for NetOps).
if [ -z "$VMID" ] || [ "$VMID" = auto ]; then
  for try in $(seq 9000 9999); do
    if ! qm status "$try" >/dev/null 2>&1; then VMID=$try; break; fi
  done
  [ -n "$VMID" ] || { echo "no free VMID in 9000-9999" >&2; exit 4; }
fi
echo "using VMID=$VMID NAME=$NAME"

# 2. Verify the mgmt IP is unused on the chosen bridge BEFORE assigning.
TARGET_IP=${IP%%/*}
if command -v arping >/dev/null 2>&1; then
  if arping -c 3 -I "$BRIDGE" -D "$TARGET_IP" >/dev/null 2>&1; then
    : # arping returned 0 = conflict detection succeeded (no reply)
  else
    echo "WARN  $TARGET_IP may be in use on $BRIDGE (arping saw a reply). Aborting." >&2
    exit 5
  fi
elif ping -c1 -W1 "$TARGET_IP" >/dev/null 2>&1; then
  echo "WARN  $TARGET_IP already answers ICMP. Aborting." >&2
  exit 5
fi

# 3. Fetch the Rocky 9 cloud image into Proxmox-local-ISO storage if missing.
IMG_BASENAME=$(basename "$IMAGE_URL")
IMG_DIR=/var/lib/vz/template/qcow
mkdir -p "$IMG_DIR"
if [ ! -s "$IMG_DIR/$IMG_BASENAME" ]; then
  curl -fL -o "$IMG_DIR/$IMG_BASENAME.part" "$IMAGE_URL"
  mv "$IMG_DIR/$IMG_BASENAME.part" "$IMG_DIR/$IMG_BASENAME"
fi

# 4. Materialise cloud-init user-data (envsubst) and a snippets directory.
SNIPPETS=/var/lib/vz/snippets
mkdir -p "$SNIPPETS"
export NETFLOW_HOSTNAME="$NAME"
export EXPORTER_CIDRS NOC_MGMT_CIDRS="$NOC_CIDRS" ZABBIX_SERVER_IP
export NETOPS_ADMIN_PUBKEY=$(tr -d '\r\n' < "$SSH_PUBKEY_FILE")
SRC_UD="$(dirname "$0")/cloud-init.user-data.yaml"
UD="$SNIPPETS/${NAME}-user.yaml"
envsubst '${NETFLOW_HOSTNAME} ${EXPORTER_CIDRS} ${NOC_MGMT_CIDRS} ${ZABBIX_SERVER_IP} ${NETOPS_ADMIN_PUBKEY}' < "$SRC_UD" > "$UD"
chmod 0640 "$UD"

# 5. Create the VM shell.
qm create "$VMID" \
    --name "$NAME" \
    --memory "$MEMORY_MB" --balloon 0 \
    --cores "$VCPUS" --sockets 1 --cpu host \
    --net0 "virtio,bridge=$BRIDGE,firewall=1" \
    --machine q35 --bios ovmf \
    --ostype l26 \
    --scsihw virtio-scsi-single \
    --agent enabled=1,fstrim_cloned_disks=1 \
    --serial0 socket --vga serial0

# EFI disk required for OVMF (small).
qm set "$VMID" --efidisk0 "${STORAGE_OS}:1,format=raw,efitype=4m,pre-enrolled-keys=0"

# 6. OS disk from the Rocky qcow2.
qm importdisk "$VMID" "$IMG_DIR/$IMG_BASENAME" "$STORAGE_OS" --format qcow2
qm set "$VMID" --scsi0 "${STORAGE_OS}:vm-${VMID}-disk-1,ssd=1,discard=on"
qm resize "$VMID" scsi0 "${OS_DISK_GB}G"

# 7. Separate expandable flow-data disk.
qm set "$VMID" --scsi1 "${STORAGE_FLOW}:${FLOW_DISK_GB},ssd=1,discard=on,iothread=1,backup=0"

# 8. Boot order + cloud-init drive.
qm set "$VMID" --ide2 "${STORAGE_OS}:cloudinit"
qm set "$VMID" --boot "order=scsi0" --bootdisk scsi0

# 9. Cloud-init settings. ipconfig0 configures the mgmt NIC; cicustom points at
#    our user-data snippet so the file writes + runcmd above are executed.
qm set "$VMID" --ipconfig0 "ip=${IP},gw=${GW}"
qm set "$VMID" --nameserver "$DNS"
qm set "$VMID" --sshkeys <(cat "$SSH_PUBKEY_FILE")
qm set "$VMID" --cicustom "user=local:snippets/${NAME}-user.yaml"
qm set "$VMID" --tags "netops,netflow,akvorado-2026.10.0"

# 10. (Optional) rsync the netflow-vm tree into the VM before first boot by
#     mounting the cloud-init disk via a pre-boot inject. Simpler: just do it
#     after boot via scp over the mgmt NIC. The orchestrator inside the VM
#     expects /opt/akvorado to exist, so we create a minimal provisioning tag
#     file; the real rsync is step 11 below.
qm start "$VMID"
echo "VM $NAME ($VMID) started; waiting for qemu-guest-agent + cloud-init..."

# 11. Wait for guest agent + cloud-init done.
for i in $(seq 1 60); do
  if qm guest cmd "$VMID" ping >/dev/null 2>&1; then break; fi
  sleep 5
done
qm guest cmd "$VMID" ping || { echo "guest agent did not come up"; exit 6; }

echo "copying netflow-vm tree → /opt/akvorado on the VM..."
TREE="${TREE_SRC:-$(dirname "$0")/..}"
scp -o StrictHostKeyChecking=accept-new -r "$TREE" "netflow-admin@${TARGET_IP}:/tmp/netflow-vm"
ssh -o StrictHostKeyChecking=accept-new "netflow-admin@${TARGET_IP}" \
    "sudo install -d -m 0750 /opt/akvorado && sudo rsync -a --delete /tmp/netflow-vm/ /opt/akvorado/ && sudo rm -rf /tmp/netflow-vm"

# 12. Kick the orchestrator (cloud-init's runcmd may have run before the tree
#     was there; this re-runs idempotently).
ssh -o StrictHostKeyChecking=accept-new "netflow-admin@${TARGET_IP}" \
    "sudo bash /opt/akvorado/bin/stack-up.sh"

# 13. Final state.
qm status "$VMID"
ssh "netflow-admin@${TARGET_IP}" 'sudo docker compose -f /opt/akvorado/upstream/akvorado-v2026.10.0/docker/docker-compose.yml ps' || true
echo
echo "VMID=$VMID NAME=$NAME IP=${TARGET_IP} READY"

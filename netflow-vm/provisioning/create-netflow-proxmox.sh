#!/usr/bin/env bash
# create-netflow-proxmox.sh — provision netflow-01 on Proxmox VE.
# Deterministic lifecycle:
#   1. Create VM shell (q35/OVMF, virtio-scsi-single, EFI disk).
#   2. Import Rocky 9 cloud image; parse the imported disk name from qm config.
#   3. Attach the imported disk as scsi0, add scsi1 flow disk, cloud-init disk.
#   4. Inject cloud-init (admin key + ephemeral bootstrap key).
#   5. Start VM; wait for qemu-guest-agent AND TCP/22 AND `cloud-init status --wait`.
#   6. Rsync the netflow-vm tree to /opt/akvorado using the EPHEMERAL private key.
#   7. Execute bin/stack-up.sh on the VM.
#   8. Revoke the ephemeral key.
set -euo pipefail

PROG=${0##*/}
NAME=netflow-01
VMID=
BRIDGE=; IP=; GW=; DNS=
EXPORTER_CIDRS=; NOC_CIDRS=; ZABBIX_SERVER_IP=
VCPUS=4; MEMORY_MB=8192; OS_DISK_GB=20; FLOW_DISK_GB=100
STORAGE_OS=; STORAGE_FLOW=
IMAGE_URL="${IMAGE_URL:-https://dl.rockylinux.org/pub/rocky/9/images/x86_64/Rocky-9-GenericCloud-Base.latest.x86_64.qcow2}"
SSH_PUBKEY_FILE="${NETOPS_ADMIN_PUBKEY_FILE:-/root/.ssh/netops-admin.pub}"
SSH_PRIVKEY_FILE=""         # if set, used for bootstrap scp/ssh (matches --ssh-pubkey-file)
TREE_SRC="${TREE_SRC:-}"
BOOT_KEY_DIR=""             # ephemeral keypair goes here when SSH_PRIVKEY_FILE is not provided

usage() {
  cat >&2 <<EOF
usage: $PROG --bridge <vmbrN> --ip <A.B.C.D/mask> --gw <A.B.C.D> --dns <A.B.C.D>
             --exporter-cidrs <csv> --noc-cidrs <csv> --zabbix-ip <A.B.C.D>
             --storage-os <datastore> --storage-flow <datastore>
             [--name netflow-01] [--vmid auto] [--vcpus 4] [--memory-mb 8192]
             [--os-disk-gb 20] [--flow-disk-gb 100]
             [--image-url ...] [--ssh-pubkey-file /path/key.pub]
             [--ssh-private-key-file /path/key]
             [--tree-src /path/to/netflow-vm]

If --ssh-private-key-file is omitted, an ephemeral keypair is generated for
bootstrap only; its public half is appended to the VM's authorized_keys at
first boot and the private half lives under /tmp for the duration of this
run. The permanent --ssh-pubkey-file is also injected.
EOF
}
while [[ $# -gt 0 ]]; do
  case "$1" in
    --name) NAME="$2"; shift 2;; --vmid) VMID="$2"; shift 2;;
    --bridge) BRIDGE="$2"; shift 2;; --ip) IP="$2"; shift 2;;
    --gw) GW="$2"; shift 2;; --dns) DNS="$2"; shift 2;;
    --exporter-cidrs) EXPORTER_CIDRS="$2"; shift 2;;
    --noc-cidrs) NOC_CIDRS="$2"; shift 2;;
    --zabbix-ip) ZABBIX_SERVER_IP="$2"; shift 2;;
    --vcpus) VCPUS="$2"; shift 2;; --memory-mb) MEMORY_MB="$2"; shift 2;;
    --os-disk-gb) OS_DISK_GB="$2"; shift 2;; --flow-disk-gb) FLOW_DISK_GB="$2"; shift 2;;
    --storage-os) STORAGE_OS="$2"; shift 2;; --storage-flow) STORAGE_FLOW="$2"; shift 2;;
    --image-url) IMAGE_URL="$2"; shift 2;;
    --ssh-pubkey-file) SSH_PUBKEY_FILE="$2"; shift 2;;
    --ssh-private-key-file) SSH_PRIVKEY_FILE="$2"; shift 2;;
    --tree-src) TREE_SRC="$2"; shift 2;;
    -h|--help) usage; exit 0;;
    *) echo "unknown arg: $1" >&2; usage; exit 2;;
  esac
done
for v in BRIDGE IP GW DNS EXPORTER_CIDRS NOC_CIDRS ZABBIX_SERVER_IP STORAGE_OS STORAGE_FLOW; do
  [ -n "${!v}" ] || { echo "missing --$(echo "$v" | tr '[:upper:]_' '[:lower:]-')" >&2; exit 2; }
done
command -v qm   >/dev/null || { echo "qm not found — run this on a Proxmox host" >&2; exit 3; }
command -v pvesm >/dev/null || { echo "pvesm not found — run this on a Proxmox host" >&2; exit 3; }
[ -s "$SSH_PUBKEY_FILE" ] || { echo "missing $SSH_PUBKEY_FILE" >&2; exit 2; }

# 0. SSH bootstrap keypair.
if [ -z "$SSH_PRIVKEY_FILE" ]; then
  BOOT_KEY_DIR=$(mktemp -d /tmp/netflow-bootkey.XXXXXX)
  ssh-keygen -t ed25519 -N '' -f "$BOOT_KEY_DIR/boot" -C "netflow-boot-$(date -u +%Y%m%dT%H%M%S)" >/dev/null
  SSH_PRIVKEY_FILE="$BOOT_KEY_DIR/boot"
  BOOT_PUBKEY_FILE="$BOOT_KEY_DIR/boot.pub"
  echo "ephemeral bootstrap keypair in $BOOT_KEY_DIR"
else
  BOOT_PUBKEY_FILE="${SSH_PRIVKEY_FILE}.pub"
  [ -s "$BOOT_PUBKEY_FILE" ] || { echo "missing $BOOT_PUBKEY_FILE (expected alongside --ssh-private-key-file)" >&2; exit 2; }
fi
cleanup_bootkey() { [ -n "$BOOT_KEY_DIR" ] && rm -rf "$BOOT_KEY_DIR"; }
trap cleanup_bootkey EXIT

# 1. Free VMID.
if [ -z "$VMID" ] || [ "$VMID" = auto ]; then
  for try in $(seq 9000 9999); do
    qm status "$try" >/dev/null 2>&1 || { VMID=$try; break; }
  done
  [ -n "$VMID" ] || { echo "no free VMID in 9000-9999" >&2; exit 4; }
fi
echo "VMID=$VMID NAME=$NAME"

# 2. Mgmt IP conflict check.
TARGET_IP=${IP%%/*}
if command -v arping >/dev/null 2>&1; then
  if ! arping -c 3 -I "$BRIDGE" -D "$TARGET_IP" >/dev/null 2>&1; then
    echo "WARN  $TARGET_IP may be in use on $BRIDGE (arping saw a reply). Aborting." >&2
    exit 5
  fi
elif ping -c1 -W1 "$TARGET_IP" >/dev/null 2>&1; then
  echo "WARN  $TARGET_IP already answers ICMP. Aborting." >&2
  exit 5
fi

# 3. Rocky image.
IMG_BASENAME=$(basename "$IMAGE_URL")
IMG_DIR=/var/lib/vz/template/qcow
mkdir -p "$IMG_DIR"
if [ ! -s "$IMG_DIR/$IMG_BASENAME" ]; then
  curl -fL -o "$IMG_DIR/$IMG_BASENAME.part" "$IMAGE_URL"
  mv "$IMG_DIR/$IMG_BASENAME.part" "$IMG_DIR/$IMG_BASENAME"
fi

# 4. cloud-init user-data snippet (envsubst).
SNIPPETS=/var/lib/vz/snippets
mkdir -p "$SNIPPETS"
export NETFLOW_HOSTNAME="$NAME"
export EXPORTER_CIDRS NOC_MGMT_CIDRS="$NOC_CIDRS" ZABBIX_SERVER_IP
export NETOPS_ADMIN_PUBKEY=$(tr -d '\r\n' < "$SSH_PUBKEY_FILE")
export BOOT_PUBKEY=$(tr -d '\r\n' < "$BOOT_PUBKEY_FILE")
SRC_UD="$(dirname "$0")/cloud-init.user-data.yaml"
UD="$SNIPPETS/${NAME}-user.yaml"
envsubst '${NETFLOW_HOSTNAME} ${EXPORTER_CIDRS} ${NOC_MGMT_CIDRS} ${ZABBIX_SERVER_IP} ${NETOPS_ADMIN_PUBKEY} ${BOOT_PUBKEY}' < "$SRC_UD" > "$UD"
chmod 0640 "$UD"

# 5. Create VM shell + EFI.
qm create "$VMID" \
    --name "$NAME" --memory "$MEMORY_MB" --balloon 0 \
    --cores "$VCPUS" --sockets 1 --cpu host \
    --net0 "virtio,bridge=$BRIDGE,firewall=1" \
    --machine q35 --bios ovmf --ostype l26 \
    --scsihw virtio-scsi-single \
    --agent enabled=1,fstrim_cloned_disks=1 \
    --serial0 socket --vga serial0
qm set "$VMID" --efidisk0 "${STORAGE_OS}:1,format=raw,efitype=4m,pre-enrolled-keys=0"

# 6. Import OS disk — DETERMINISTIC parse of the resulting unused entry.
BEFORE_UNUSED=$(qm config "$VMID" | awk -F: '/^unused[0-9]+:/' | sort -u)
qm importdisk "$VMID" "$IMG_DIR/$IMG_BASENAME" "$STORAGE_OS" --format qcow2
AFTER_UNUSED=$(qm config "$VMID" | awk '/^unused[0-9]+:/' )
IMPORTED_LINE=$(diff <(printf '%s\n' "$BEFORE_UNUSED") <(printf '%s\n' "$AFTER_UNUSED") | awk '/^> /{sub(/^> /,""); print; exit}')
IMPORTED_DISK=$(echo "$IMPORTED_LINE" | awk -F: '{print $2":"$3}' | tr -d ' ')
[ -n "$IMPORTED_DISK" ] || { echo "failed to parse imported disk from qm config"; exit 6; }
echo "imported disk: $IMPORTED_DISK"
qm set "$VMID" --scsi0 "$IMPORTED_DISK,ssd=1,discard=on"
qm resize "$VMID" scsi0 "${OS_DISK_GB}G"

# 7. Flow data disk + cloud-init disk + boot order.
qm set "$VMID" --scsi1 "${STORAGE_FLOW}:${FLOW_DISK_GB},ssd=1,discard=on,iothread=1,backup=0"
qm set "$VMID" --ide2 "${STORAGE_OS}:cloudinit"
qm set "$VMID" --boot "order=scsi0" --bootdisk scsi0

# 8. cloud-init settings.
qm set "$VMID" --ipconfig0 "ip=${IP},gw=${GW}"
qm set "$VMID" --nameserver "$DNS"
qm set "$VMID" --cicustom "user=local:snippets/${NAME}-user.yaml"
qm set "$VMID" --tags "netops,netflow,akvorado-2026.10.0"

# 9. Start + full ready wait.
qm start "$VMID"
echo "VM $NAME ($VMID) started; waiting for qemu-guest-agent..."
for i in $(seq 1 60); do
  qm guest cmd "$VMID" ping >/dev/null 2>&1 && break
  sleep 5
done
qm guest cmd "$VMID" ping || { echo "guest agent did not come up"; exit 7; }

echo "waiting for TCP/22 on $TARGET_IP..."
for i in $(seq 1 60); do
  (echo > /dev/tcp/${TARGET_IP}/22) 2>/dev/null && break
  sleep 5
done

SSH_OPTS=(-i "$SSH_PRIVKEY_FILE" -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=5 -o BatchMode=yes)
SSH_HOST="netflow-admin@${TARGET_IP}"

echo "waiting for cloud-init status --wait to complete (max 10 min)..."
if ! ssh "${SSH_OPTS[@]}" "$SSH_HOST" "cloud-init status --wait" >/dev/null 2>&1; then
  echo "cloud-init did not reach done state. Capture: cloud-init status --long" >&2
  ssh "${SSH_OPTS[@]}" "$SSH_HOST" "cloud-init status --long || true" | sed 's/^/  /'
  exit 8
fi
echo "cloud-init done"

# 10. Rsync the netflow-vm tree to /opt/akvorado.
TREE="${TREE_SRC:-$(cd "$(dirname "$0")/.." && pwd)}"
echo "rsyncing $TREE → /opt/akvorado"
rsync -az -e "ssh ${SSH_OPTS[*]}" --delete \
    --exclude='.digests.lock*' --exclude='bin/__pycache__' \
    "$TREE/" "${SSH_HOST}:/tmp/netflow-vm/"
ssh "${SSH_OPTS[@]}" "$SSH_HOST" "sudo install -d -m 0750 /opt/akvorado && sudo rsync -a --delete /tmp/netflow-vm/ /opt/akvorado/ && sudo rm -rf /tmp/netflow-vm"

# 11. Apply firewalld (now that the real script is on disk), then stack-up.
ssh "${SSH_OPTS[@]}" "$SSH_HOST" "sudo /opt/akvorado/provisioning/firewalld-apply.sh '${EXPORTER_CIDRS}' '${NOC_CIDRS}' '${ZABBIX_SERVER_IP}'"
ssh "${SSH_OPTS[@]}" "$SSH_HOST" "sudo bash /opt/akvorado/bin/stack-up.sh"

# 12. Revoke the ephemeral bootstrap key (admin key remains).
if [ -n "$BOOT_KEY_DIR" ]; then
  echo "revoking ephemeral bootstrap key from authorized_keys"
  BOOT_KEY_CONTENT=$(cat "$BOOT_PUBKEY_FILE")
  ssh "${SSH_OPTS[@]}" "$SSH_HOST" "sudo sed -i \"\\|$(printf '%s' "$BOOT_KEY_CONTENT" | sed 's|[/&]|\\&|g')|d\" /home/netflow-admin/.ssh/authorized_keys" || true
fi

# 13. Final state.
qm status "$VMID"
ssh "${SSH_OPTS[@]}" "$SSH_HOST" 'sudo docker compose -f /opt/akvorado/upstream/akvorado-v2026.10.0/docker/docker-compose.yml ps' || true
echo
echo "VMID=$VMID NAME=$NAME IP=${TARGET_IP} READY"

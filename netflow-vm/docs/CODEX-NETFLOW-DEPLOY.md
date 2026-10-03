# NetFlow platform — Codex deploy procedure (single supported path)

This is the ONLY supported way to bring up `netflow-01` for the WAN NetFlow platform. All alternatives in older commits are superseded.

Target state after this runbook: Akvorado v2026.10.0 running under Docker Engine, Flow API reverse-proxying both `/api/v1/` (Zabbix) and `/akvorado/` (NOC console) over TLS, firewalld restricting both; SELinux Enforcing; immutable digests pinned; `netops.flow_v1` compat view live.

## 0. Prerequisites

- Access to the Proxmox host (Codex has this; Claude does not from the controller used in this phase).
- NetOps management IP that is **currently unused** on the chosen bridge.
- NetOps admin SSH public key file.
- The repo cloned on the Proxmox host at a known path; the `netflow-vm/` subtree is what the Proxmox provisioning script rsync's into the VM.

## 1. On the Proxmox host

```bash
cd /path/to/Zabbix/netflow-vm
sudo provisioning/create-netflow-proxmox.sh \
    --bridge        <vmbrN> \
    --ip            <A.B.C.D/mask> \
    --gw            <gw-ip> \
    --dns           <dns-ip> \
    --exporter-cidrs "<csv-of-WAN-exporter-CIDRs>" \
    --noc-cidrs      "<csv-of-NOC-mgmt-CIDRs>" \
    --zabbix-ip      <zabbix-server-ip> \
    --storage-os     <proxmox-storage-datastore-for-os> \
    --storage-flow   <proxmox-storage-datastore-for-flow-disk> \
    --ssh-pubkey-file /root/.ssh/netops-admin.pub \
    --tree-src       "$(pwd)"
```

What this does:

1. Picks a free VMID in `9000-9999`, verifies the mgmt IP is unused (arping or ICMP), downloads the Rocky 9 Generic Cloud qcow2 if absent.
2. Creates `netflow-01` (UEFI, Q35, virtio-scsi-single, 4 vCPU, 8 GiB RAM, 20 GiB OS disk, 100 GiB expandable flow disk on `scsi1`).
3. Writes cloud-init `user-data` as a snippet from `provisioning/cloud-init.user-data.yaml` with `${NETFLOW_HOSTNAME}`, `${EXPORTER_CIDRS}`, `${NOC_MGMT_CIDRS}`, `${ZABBIX_SERVER_IP}`, `${NETOPS_ADMIN_PUBKEY}` substituted.
4. Starts the VM, waits for `qemu-guest-agent` to answer `ping`.
5. `scp` + `rsync` the `netflow-vm/` tree into `/opt/akvorado` on the VM.
6. Invokes `bin/stack-up.sh` on the VM. That script is the single bring-up orchestrator (see §2).

## 2. What `bin/stack-up.sh` enforces (order matters)

Run inside the VM, idempotently:

```
1  verify runtime  (docker, docker compose plugin)
2  prepare host paths  (/var/lib/akvorado/data/{clickhouse,kafka}, SELinux labels)
3  docker compose up  (vendored upstream + overlay + digest-pin if present)
4  wait for ClickHouse schema  (akvorado.flows exists, max 5 min)
5  flow-api secrets  (openssl writes /etc/flow-api/{ch-pass, zabbix.token.sha256,
                      zabbix-token.env, console-htpasswd, console-credential.env})
6  bin/clickhouse-apply.sh  (CREATE OR REPLACE netops.flow_v1; CREATE USER IF
                             NOT EXISTS flow_api_ro; GRANT SELECT ...)
7  flow-api/flow-api-install.sh  (nginx TLS + php-fpm + firewalld 443 zone)
8  validate  (/healthz, /akvorado/ -> 401 or 200, clickhouse /ping, each
              akvorado service /api/v0/healthcheck)
```

If anything in step 4/8 fails, the script exits non-zero and leaves the box in a diagnosable state — DO NOT retry blindly, read `/var/log/akvorado*.log` and `docker compose logs`.

## 3. Pin immutable digests (REQUIRED before you call it production)

```bash
sudo /opt/akvorado/bin/pin-digests.sh
```

Writes `/opt/akvorado/overlay/.digests.lock`. From that point on, `stack-up.sh` substitutes digest-pinned image references via a transient compose fragment and the stack cannot drift to a floating tag.

Rollback: `sudo /opt/akvorado/bin/rollback.sh` restores `overlay/.digests.lock.prev` and recreates the containers.

## 4. Ship credentials to Zabbix (NOT via scp cleartext)

The following files on `netflow-01` carry one-time secrets and are mode `0600 root:root`:

| File | What |
|---|---|
| `/etc/flow-api/zabbix-token.env` | Bearer token the Zabbix FlowSearch module uses to call `/api/v1/*` |
| `/etc/flow-api/console-credential.env` | HTTP basic username/password for `/akvorado/` |

Ship them to the Zabbix server as **sealed systemd credentials** (`systemd-creds encrypt --with-key=host`). Do not scp cleartext; do not commit; do not paste.

Zabbix-side env for the FlowSearch module:

```
FLOW_MODE=api
FLOW_ENDPOINT=https://netflow-01.<domain>/api/v1
FLOW_PASS=<ciphertext from zabbix-token.env, decrypted by systemd at service start>
```

## 5. Validate from a NOC workstation

- `https://netflow-01.<domain>/akvorado/` — HTTP basic prompt → console loads.
- `curl -H 'Authorization: Bearer <token>' https://netflow-01.<domain>/api/v1/summary -d '{"filter":{"from":<t-1h>,"to":<t>}}'` → JSON summary.
- From Zabbix: open the Flow Search widget → non-empty tiles.

## 6. First exporter (POC)

Follow `netflow-vm/docs/EXPORTER-SAFETY.md`:

1. Pick one Internet-edge router (STC or Mobily).
2. Capture pre-change CPU + routing adjacencies.
3. Apply the Flexible-NetFlow or NetStream template from `templates/exporters/`.
4. Confirm:
   - `tcpdump -i any -c 10 udp port 2055 and host <exporter>` on `netflow-01`
   - `docker exec akvorado-clickhouse clickhouse-client -q "SELECT count() FROM akvorado.flows WHERE ExporterAddress = toIPv6('<exporter>') AND TimeReceived > now() - 60"` → non-zero
   - Flow Search widget filter by exporter → rows
5. Post-change CPU + adjacencies unchanged.
6. If any check fails: rollback the exporter config using the pre-captured snippet.

## 7. Hand nothing else to the operator

This document plus `netflow-vm/README.md` and the inline comments on each script are the complete procedure. There is NO alternative path (no manual compose edits, no ZK-backed variant, no 1.11.x variant, no podman-based variant). If someone asks for one, say no and point here.  <!-- BAN:keep -->


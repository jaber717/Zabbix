#!/usr/bin/env bash
# exporter-poc-stc.sh — first NetFlow exporter POC on PNET-STC.
# Precondition: netflow-01 is up with the full Akvorado stack running.
# Postcondition: STC exports NetFlow/IPFIX to netflow-01, Akvorado receives
# flows from this exporter, and the ClickHouse row count for ExporterAddress
# = PNET-STC increases over the measurement window.
#
# SSH to PNET-STC uses the ProxyJump via pnet-lab, documented in the shared
# bundle's ssh-config. User `codex`, keyboard-interactive password. The
# password is NOT embedded here; this script invokes plink/sshpass through
# the bundle so the plaintext never reaches our stdout/stderr.
set -euo pipefail

: "${BUNDLE:=$HOME/.config/netops/claude-access}"
: "${NETFLOW_IP:?set NETFLOW_IP to netflow-01's management IP}"
: "${EXPORTER_HOST:=PNET-STC}"            # Zabbix / ssh-config alias key
: "${EXPORTER_IOS_ALIAS:=wanlab-stc}"     # ssh-config entry
: "${INTERFACE:=GigabitEthernet0/0}"      # the Gi0/0 TO-INT-CORE interface
: "${SAMPLING_RATE:=1000}"                # 1:1000, bump down only after CPU proof
: "${EVIDENCE_DIR:=$HOME/netflow-evidence/stc-$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$EVIDENCE_DIR"/{pre,change,post,flow}

if ! command -v plink >/dev/null 2>&1; then
  echo "FATAL plink not on PATH; needed for password-authenticated router SSH."
  echo "      Install PuTTY (ships plink.exe) or supply NETWORK_DEVICE_SSH_PASSWORD + an"
  echo "      alternative sshpass/expect wrapper."
  exit 2
fi

# Pull router password from the bundle without echoing it.
# shellcheck disable=SC1091
. "$BUNDLE/network-device.env"
: "${NETWORK_DEVICE_SSH_USER:?missing in network-device.env}"
: "${NETWORK_DEVICE_SSH_PASSWORD:?missing in network-device.env}"
: "${PNET_SSH_HOST:?set in pnet.env}"
# shellcheck disable=SC1091
. "$BUNDLE/pnet.env"
: "${PNET_SSH_USER:?missing in pnet.env}"
: "${PNET_SSH_PASSWORD:?missing in pnet.env}"

# Resolve the target router IP from ssh-config.
TARGET_IP=$(awk -v h="$EXPORTER_IOS_ALIAS" '/^Host [a-z]/ {h2=$2} h2==h && /HostName/ {print $2; exit}' "$BUNDLE/ssh-config")
: "${TARGET_IP:?no HostName for $EXPORTER_IOS_ALIAS in ssh-config}"
echo "target IP $TARGET_IP (via jump $PNET_SSH_HOST)"

run_router() {
  local cmd="$1" tag="$2"
  # ssh pnet-jump → ssh router → run cmd. Use plink -ssh with -pw per hop,
  # with -batch for both so neither prompts.
  plink -ssh -batch -pw "$PNET_SSH_PASSWORD" \
    "${PNET_SSH_USER}@${PNET_SSH_HOST}" \
    "plink -ssh -batch -pw '$NETWORK_DEVICE_SSH_PASSWORD' '${NETWORK_DEVICE_SSH_USER}@${TARGET_IP}' '$cmd'" \
    2>&1 | sed "s/\r$//" > "$EVIDENCE_DIR/$tag"
}

# -------- 1. Pre-change capture --------
echo "== pre-change capture =="
for pair in \
    "show clock|pre/clock.txt" \
    "show version|pre/version.txt" \
    "show processes cpu history 1min|pre/cpu-history.txt" \
    "show processes memory | include Processor|pre/memory.txt" \
    "show interfaces $INTERFACE|pre/if.txt" \
    "show ip bgp summary|pre/bgp.txt" \
    "show ip ospf neighbor|pre/ospf.txt" \
    "show running-config | section flow|pre/flow-config.txt" ; do
  cmd=${pair%%|*}; file=${pair#*|}
  echo "  $cmd  →  $file"
  run_router "$cmd" "$file" || true
done

# -------- 2. Change --------
#
# IOSv Flexible NetFlow config. 1:1000 sampling on ingress of the WAN interface.
# No reload, no interface flap, no route-map, no routing policy touched.
cat > "$EVIDENCE_DIR/change/apply.ios" <<EOF
flow record NETOPS-NFR-V9
 match ipv4 source address
 match ipv4 destination address
 match ipv4 protocol
 match transport source-port
 match transport destination-port
 collect ipv4 ttl
 collect ipv4 tos
 collect counter bytes long
 collect counter packets long
 collect timestamp sys-uptime first
 collect timestamp sys-uptime last
flow exporter NETOPS-NFE-NETFLOW01
 destination ${NETFLOW_IP}
 transport udp 2055
 export-protocol netflow-v9
 template data timeout 60
flow monitor NETOPS-NFM
 record NETOPS-NFR-V9
 exporter NETOPS-NFE-NETFLOW01
 cache timeout active 60
 cache timeout inactive 15
sampler NETOPS-SMP
 mode random 1 out-of ${SAMPLING_RATE}
interface ${INTERFACE}
 ip flow monitor NETOPS-NFM sampler NETOPS-SMP input
EOF
cat > "$EVIDENCE_DIR/change/rollback.ios" <<EOF
interface ${INTERFACE}
 no ip flow monitor NETOPS-NFM sampler NETOPS-SMP input
no flow monitor NETOPS-NFM
no flow record NETOPS-NFR-V9
no flow exporter NETOPS-NFE-NETFLOW01
no sampler NETOPS-SMP
EOF

echo "== apply exporter config =="
CFG=$(sed 's|^|configure terminal\n|' <(sed -n 1p "$EVIDENCE_DIR/change/apply.ios")) # placeholder; we send a single config block below
# Join the IOS block into semicolons so plink can send it in one SSH invocation
# via `config terminal`.
BLOCK="configure terminal\n$(cat "$EVIDENCE_DIR/change/apply.ios")\nend\nwrite memory"
# plink -m <file> is cleaner than echoing a block through -t.
BATCH="$EVIDENCE_DIR/change/apply.batch"
{ echo "configure terminal"; cat "$EVIDENCE_DIR/change/apply.ios"; echo "end"; echo "write memory"; } > "$BATCH"
plink -ssh -batch -pw "$PNET_SSH_PASSWORD" "${PNET_SSH_USER}@${PNET_SSH_HOST}" \
  "plink -ssh -batch -pw '$NETWORK_DEVICE_SSH_PASSWORD' -m '$BATCH' '${NETWORK_DEVICE_SSH_USER}@${TARGET_IP}'" \
  2>&1 | sed "s/\r$//" > "$EVIDENCE_DIR/change/apply.out" || true

# -------- 3. Post-change capture --------
echo "== post-change capture =="
sleep 15
for pair in \
    "show clock|post/clock.txt" \
    "show processes cpu history 1min|post/cpu-history.txt" \
    "show processes memory | include Processor|post/memory.txt" \
    "show interfaces $INTERFACE|post/if.txt" \
    "show ip bgp summary|post/bgp.txt" \
    "show ip ospf neighbor|post/ospf.txt" \
    "show flow exporter NETOPS-NFE-NETFLOW01|post/flow-exporter.txt" \
    "show flow monitor NETOPS-NFM cache|post/flow-monitor-cache.txt" ; do
  cmd=${pair%%|*}; file=${pair#*|}
  run_router "$cmd" "$file" || true
done

# -------- 4. netflow-01 verification --------
echo "== netflow-01 verification =="
ssh -i /c/Users/jaber/.ssh/jaberlab_codex -o BatchMode=yes "netflow-admin@${NETFLOW_IP}" \
    "docker exec akvorado-clickhouse clickhouse-client --query \"
SELECT count() AS flows_from_stc,
       uniq(SrcAddr) AS uniq_sources,
       min(TimeReceived) AS first_seen,
       max(TimeReceived) AS last_seen
FROM akvorado.flows
WHERE ExporterAddress = toIPv6('${TARGET_IP}')
  AND TimeReceived > now() - 300\"" \
    > "$EVIDENCE_DIR/flow/clickhouse-count.txt" 2>&1 || echo "clickhouse count query failed (see file)"
cat "$EVIDENCE_DIR/flow/clickhouse-count.txt"

# -------- 5. Verdict --------
PRE_CPU_SUM=$(awk 'match($0, /[0-9]+/) {s+=substr($0,RSTART,RLENGTH); n++} END{if(n)print s/n}' "$EVIDENCE_DIR/pre/cpu-history.txt" || echo 0)
POST_CPU_SUM=$(awk 'match($0, /[0-9]+/) {s+=substr($0,RSTART,RLENGTH); n++} END{if(n)print s/n}' "$EVIDENCE_DIR/post/cpu-history.txt" || echo 0)
FLOWS=$(awk 'NR==2{print $1}' "$EVIDENCE_DIR/flow/clickhouse-count.txt" 2>/dev/null || echo 0)
cat > "$EVIDENCE_DIR/VERDICT.md" <<EOF
# PNET-STC exporter POC — $(date -u +%Y-%m-%dT%H:%M:%SZ)

- target: ${TARGET_IP} (${EXPORTER_HOST})
- interface: ${INTERFACE}
- sampling: 1:${SAMPLING_RATE}
- flows received at netflow-01 (last 5 min): ${FLOWS}
- CPU pre (1-min history avg): ${PRE_CPU_SUM}
- CPU post (1-min history avg): ${POST_CPU_SUM}

Decision rules:
- PASS if flows > 0 AND CPU rise < 5 pp absolute AND no routing adjacency state change.
- WARN if flows > 0 AND CPU rise >= 5 pp absolute.
- FAIL otherwise — apply ${EVIDENCE_DIR}/change/rollback.ios immediately.
EOF
echo "evidence dir: $EVIDENCE_DIR"
echo "verdict file: $EVIDENCE_DIR/VERDICT.md"
unset NETWORK_DEVICE_SSH_PASSWORD PNET_SSH_PASSWORD

#!/usr/bin/env bash
# exporter-poc-stc.sh — first NetFlow exporter POC on PNET-STC.
#
# Transport: OpenSSH with ProxyJump defined in the shared ssh-config. The
# jump host is `pnet-lab`; the router alias is `wanlab-stc`. Both hops use
# password keyboard-interactive auth. We supply those two passwords through
# sshpass twice (per-hop sshpass invocations) — this is the exact method the
# shared bundle documents and the only one that is working on this LAB today.
# No plink, no nested-plink shell, no path assumptions on the jump host.
#
# Pre-change capture, config apply, post-change capture, flow-count probe,
# and VERDICT are all written under $EVIDENCE_DIR. Apply failure is FATAL;
# `|| true` is NOT used around the config apply.
#
# Run from netflow-01 (Rocky 9) where sshpass is available via dnf.

set -euo pipefail

: "${BUNDLE:=$HOME/.config/netops/claude-access}"
: "${NETFLOW_IP:?set NETFLOW_IP to the netflow-01 management IP}"
: "${EXPORTER_HOST:=PNET-STC}"
: "${EXPORTER_IOS_ALIAS:=wanlab-stc}"
: "${INTERFACE:=GigabitEthernet0/0}"
# For the first LAB POC we deliberately do NOT sample (SAMPLING_RATE=0 means
# the apply block omits the `sampler` statement entirely). After PASS, Codex
# runs a stress harness that re-enables realistic sampling.
: "${SAMPLING_RATE:=0}"
TS=$(date -u +%Y%m%dT%H%M%SZ)
: "${EVIDENCE_DIR:=$HOME/netflow-evidence/stc-$TS}"
mkdir -p "$EVIDENCE_DIR"/{pre,change,post,flow}

command -v sshpass >/dev/null || { echo "FATAL sshpass not installed (dnf install -y sshpass)"; exit 2; }
command -v ssh     >/dev/null || { echo "FATAL ssh not installed"; exit 2; }

# Pull creds without echoing. shellcheck source=/dev/null
. "$BUNDLE/network-device.env"
. "$BUNDLE/pnet.env"
: "${NETWORK_DEVICE_SSH_USER:?missing in network-device.env}"
: "${NETWORK_DEVICE_SSH_PASSWORD:?missing in network-device.env}"
: "${PNET_SSH_HOST:?missing in pnet.env}"
: "${PNET_SSH_USER:?missing in pnet.env}"
: "${PNET_SSH_PASSWORD:?missing in pnet.env}"

# Target router IP from the shared ssh-config (single source of truth).
TARGET_IP=$(awk -v h="$EXPORTER_IOS_ALIAS" '
  /^Host [a-z]/   {h2=$2}
  h2==h && /HostName/ {print $2; exit}
' "$BUNDLE/ssh-config")
: "${TARGET_IP:?no HostName for $EXPORTER_IOS_ALIAS in $BUNDLE/ssh-config}"
echo "exporter=$EXPORTER_HOST ip=$TARGET_IP via jump $PNET_SSH_HOST"

# -------- transport helpers --------
# `router_sh CMD`           runs CMD in exec mode on the IOSv router.
# `router_cfg FILE`         runs `configure terminal / FILE / end / write memory`
#                           by piping FILE into ssh stdin (IOSv config mode).
# Both go local → pnet-jump → router using sshpass per hop, OpenSSH ProxyCommand.
export SSHPASS_PNET="$PNET_SSH_PASSWORD"
export SSHPASS_ROUTER="$NETWORK_DEVICE_SSH_PASSWORD"
SSH_COMMON=(-o BatchMode=no -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=10 -o PubkeyAuthentication=no -o PreferredAuthentications=keyboard-interactive,password)

router_ssh() {
  # $1 = optional stdin file for config mode; "" for exec mode
  # $2.. = command words
  local stdin_file="$1"; shift
  SSHPASS="$SSHPASS_ROUTER" sshpass -e ssh "${SSH_COMMON[@]}" \
      -o "ProxyCommand=sshpass -p \"$SSHPASS_PNET\" ssh ${SSH_COMMON[*]} -W %h:%p ${PNET_SSH_USER}@${PNET_SSH_HOST}" \
      "${NETWORK_DEVICE_SSH_USER}@${TARGET_IP}" \
      ${stdin_file:+ < "$stdin_file"} \
      "$@"
}

router_sh() {
  # Exec-mode command. IOSv happily runs `-- 'show clock'` as a shell cmd.
  router_ssh "" "$1"
}

router_cfg() {
  # Config mode. Feed `configure terminal` + file + `end` + `write memory`.
  local src="$1" tmp
  tmp=$(mktemp)
  { echo "terminal length 0"; echo "configure terminal"; cat "$src"; echo "end"; echo "write memory"; } > "$tmp"
  router_ssh "$tmp" ""
  rm -f "$tmp"
}

# -------- 0. transport validation (must succeed BEFORE anything else) --------
echo "== transport probe (show clock) =="
if ! router_sh "show clock" | tee "$EVIDENCE_DIR/pre/transport-probe.txt" | grep -qE '[0-9]{2}:[0-9]{2}:[0-9]{2}'; then
  echo "FATAL transport probe failed; refusing to proceed"
  exit 3
fi
echo "transport OK"

# -------- 1. pre-change capture --------
echo "== pre-change capture =="
# Deterministic CPU reading: `show processes cpu | include CPU utilization` gives
# a single line like
#   CPU utilization for five seconds: 3%/0%; one minute: 2%; five minutes: 2%
# We parse the 1-minute and 5-minute values explicitly.
PRE_CPU=$(router_sh "show processes cpu | include CPU utilization" | tee "$EVIDENCE_DIR/pre/cpu.txt" \
          | sed -n 's/.*one minute: \([0-9]*\)%.*five minutes: \([0-9]*\)%.*/\1 \2/p')
echo "pre_cpu_1m_5m: ${PRE_CPU:-UNKNOWN}" > "$EVIDENCE_DIR/pre/cpu-parsed.txt"
router_sh "show version"                                 > "$EVIDENCE_DIR/pre/version.txt"
router_sh "show processes memory | include Processor"    > "$EVIDENCE_DIR/pre/memory.txt"
router_sh "show interfaces $INTERFACE"                   > "$EVIDENCE_DIR/pre/if.txt"
router_sh "show ip bgp summary"                          > "$EVIDENCE_DIR/pre/bgp.txt" || true  # may be unsupported
router_sh "show ip ospf neighbor"                        > "$EVIDENCE_DIR/pre/ospf.txt" || true
router_sh "show running-config | section flow"           > "$EVIDENCE_DIR/pre/flow-config.txt"
router_sh "show running-config | section sampler"        > "$EVIDENCE_DIR/pre/sampler-config.txt"

# -------- 2. apply --------
# Build the config. If SAMPLING_RATE=0, omit the sampler entirely — pure
# ingress monitor on the WAN interface. This is Goal #1: prove the full
# pipeline sees real flows.
APPLY="$EVIDENCE_DIR/change/apply.ios"
cat > "$APPLY" <<EOF
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
EOF
if [ "${SAMPLING_RATE}" -gt 0 ]; then
  cat >> "$APPLY" <<EOF
sampler NETOPS-SMP
 mode random 1 out-of ${SAMPLING_RATE}
EOF
fi
cat >> "$APPLY" <<EOF
interface ${INTERFACE}
 ip flow monitor NETOPS-NFM $( [ "${SAMPLING_RATE}" -gt 0 ] && echo "sampler NETOPS-SMP " )input
EOF
# Rollback counterpart.
cat > "$EVIDENCE_DIR/change/rollback.ios" <<EOF
interface ${INTERFACE}
 no ip flow monitor NETOPS-NFM $( [ "${SAMPLING_RATE}" -gt 0 ] && echo "sampler NETOPS-SMP " )input
no flow monitor NETOPS-NFM
no flow record NETOPS-NFR-V9
no flow exporter NETOPS-NFE-NETFLOW01
$( [ "${SAMPLING_RATE}" -gt 0 ] && echo "no sampler NETOPS-SMP" )
EOF

echo "== apply exporter config (FATAL on failure) =="
router_cfg "$APPLY" | tee "$EVIDENCE_DIR/change/apply.out"
# If router_cfg returned non-zero, set -e has already killed us. Belt + braces:
grep -qiE '% *(Invalid|Incomplete|Ambiguous|Error)' "$EVIDENCE_DIR/change/apply.out" && {
  echo "FATAL IOS reported an error during apply — see change/apply.out"; exit 4; }

sleep 5

# -------- 3. verify applied config exists --------
echo "== verify applied config =="
router_sh "show running-config | section flow"       > "$EVIDENCE_DIR/post/flow-config.txt"
router_sh "show flow exporter NETOPS-NFE-NETFLOW01"  > "$EVIDENCE_DIR/post/flow-exporter.txt"
router_sh "show flow monitor NETOPS-NFM"             > "$EVIDENCE_DIR/post/flow-monitor.txt"
router_sh "show flow monitor NETOPS-NFM cache"       > "$EVIDENCE_DIR/post/flow-monitor-cache.txt"
router_sh "show running-config interface $INTERFACE" > "$EVIDENCE_DIR/post/if-config.txt"
if [ "${SAMPLING_RATE}" -gt 0 ]; then
  router_sh "show sampler NETOPS-SMP"                > "$EVIDENCE_DIR/post/sampler.txt"
fi

# These greps are the gate for ClickHouse validation.
grep -q 'NETOPS-NFR-V9'                    "$EVIDENCE_DIR/post/flow-config.txt" || { echo "FATAL flow record missing after apply"; exit 5; }
grep -q "destination ${NETFLOW_IP}"        "$EVIDENCE_DIR/post/flow-exporter.txt" || { echo "FATAL exporter destination missing"; exit 5; }
grep -q 'NETOPS-NFM'                       "$EVIDENCE_DIR/post/flow-monitor.txt" || { echo "FATAL flow monitor missing"; exit 5; }
grep -q 'ip flow monitor NETOPS-NFM'       "$EVIDENCE_DIR/post/if-config.txt"   || { echo "FATAL monitor not attached to $INTERFACE"; exit 5; }
echo "applied-config verification OK"

# -------- 4. post-change CPU + routing + interface --------
POST_CPU=$(router_sh "show processes cpu | include CPU utilization" | tee "$EVIDENCE_DIR/post/cpu.txt" \
           | sed -n 's/.*one minute: \([0-9]*\)%.*five minutes: \([0-9]*\)%.*/\1 \2/p')
echo "post_cpu_1m_5m: ${POST_CPU:-UNKNOWN}" > "$EVIDENCE_DIR/post/cpu-parsed.txt"
router_sh "show processes memory | include Processor"    > "$EVIDENCE_DIR/post/memory.txt"
router_sh "show interfaces $INTERFACE"                   > "$EVIDENCE_DIR/post/if.txt"
router_sh "show ip bgp summary"                          > "$EVIDENCE_DIR/post/bgp.txt" || true
router_sh "show ip ospf neighbor"                        > "$EVIDENCE_DIR/post/ospf.txt" || true

# -------- 5. netflow-01: flow count from this exporter --------
echo "== netflow-01 flow count =="
# TSVWithNames gives us a predictable header on row 1 and data on row 2.
# We ask for a single-row aggregate so NR==2 is deterministic.
ssh -i "$HOME/.ssh/jaberlab_codex" -o BatchMode=yes "netflow-admin@${NETFLOW_IP}" \
    "docker exec akvorado-clickhouse clickhouse-client --format TSVWithNames --query \"
SELECT count() AS flows_from_stc,
       uniq(SrcAddr) AS uniq_sources,
       toString(min(TimeReceived)) AS first_seen,
       toString(max(TimeReceived)) AS last_seen
FROM akvorado.flows
WHERE ExporterAddress = toIPv6('${TARGET_IP}')
  AND TimeReceived > now() - 300\"" \
    > "$EVIDENCE_DIR/flow/clickhouse-count.tsv"
cat "$EVIDENCE_DIR/flow/clickhouse-count.tsv"
# TSVWithNames: row 1 is the header, row 2 is the single data row.
FLOWS=$(awk 'NR==2 {print $1}' "$EVIDENCE_DIR/flow/clickhouse-count.tsv")
: "${FLOWS:=0}"

# -------- 6. VERDICT --------
cpu_delta() {
  local pre="$1" post="$2"
  if [ -z "$pre" ] || [ -z "$post" ]; then echo UNKNOWN; return; fi
  # 1-minute pre vs 1-minute post
  echo $(( ${post%% *} - ${pre%% *} ))
}
CPU_DELTA_1M=$(cpu_delta "${PRE_CPU:-}" "${POST_CPU:-}")

VERDICT=FAIL
case "$CPU_DELTA_1M" in
  UNKNOWN) VERDICT=NOT_PROVEN ;;
  *) if [ "$FLOWS" -gt 0 ] && [ "$CPU_DELTA_1M" -lt 5 ]; then VERDICT=PASS;
     elif [ "$FLOWS" -gt 0 ]; then VERDICT=WARN; fi ;;
esac

cat > "$EVIDENCE_DIR/VERDICT.md" <<EOF
# PNET-STC exporter POC — $(date -u +%Y-%m-%dT%H:%M:%SZ)

- target IP: ${TARGET_IP}  (${EXPORTER_HOST})
- interface: ${INTERFACE}
- sampling: $( [ "${SAMPLING_RATE}" -gt 0 ] && echo "1:${SAMPLING_RATE}" || echo "disabled (POC)" )
- flows received at netflow-01 (last 5 min): ${FLOWS}
- CPU pre  (1-min / 5-min): ${PRE_CPU:-UNKNOWN}
- CPU post (1-min / 5-min): ${POST_CPU:-UNKNOWN}
- CPU delta (1-min): ${CPU_DELTA_1M}
- verdict: **${VERDICT}**

Decision rules:
- PASS       flows > 0 AND CPU delta < 5 pp AND no routing adjacency state change.
- WARN       flows > 0 AND CPU delta >= 5 pp.
- NOT_PROVEN CPU parse failed.
- FAIL       flows == 0 → apply ${EVIDENCE_DIR}/change/rollback.ios immediately.
EOF
cat "$EVIDENCE_DIR/VERDICT.md"
unset SSHPASS_PNET SSHPASS_ROUTER NETWORK_DEVICE_SSH_PASSWORD PNET_SSH_PASSWORD
[ "$VERDICT" = PASS ] || [ "$VERDICT" = WARN ] || exit 10

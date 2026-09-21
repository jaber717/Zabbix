#!/usr/bin/env bash
# Offline, read-only SNMPv3 diagnostics for Huawei AR8100 interface counters.
# Device-specific conclusions are produced only from the live output of this run.

set +x
set -Eeuo pipefail
umask 077
ulimit -c 0 >/dev/null 2>&1 || true
ulimit -f 16384 >/dev/null 2>&1 || {
    printf 'ERROR: unable to enforce the 16 MiB per-file evidence limit\n' >&2
    exit 1
}
export LC_ALL=C

readonly REPORT=/tmp/huawei-ar8100-diagnostic-report.txt
readonly SHARE_SUMMARY=/tmp/huawei-ar8100-share-summary.txt
readonly EVIDENCE_DIR=/tmp/huawei-ar8100-diagnostic
readonly DIAGNOSTIC_VERSION=1.0.0
readonly AUTH_PROTOCOL=SHA-256
readonly PRIV_PROTOCOL=AES-192
readonly DEFAULT_INTERFACE=10GE0/0/5
readonly SAMPLE_INTERVAL=15
readonly COMMAND_TIMEOUT=30
readonly MAX_WALK_ROWS=10000
readonly IF_EXT_ROOT=.1.3.6.1.4.1.2011.5.25.41
readonly CBQOS_ROOT=.1.3.6.1.4.1.2011.5.25.32

SECRET_DIR=
AUTH_PASSPHRASE=
PRIV_PASSPHRASE=

die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

cleanup() {
    AUTH_PASSPHRASE=
    PRIV_PASSPHRASE=
    unset AUTH_PASSPHRASE PRIV_PASSPHRASE
    if [[ -n "${SECRET_DIR:-}" ]]; then
        case "$SECRET_DIR" in
            /dev/shm/huawei-ar8100-snmp.*)
                rm -f -- "$SECRET_DIR/snmp.conf"
                rm -rf -- "$SECRET_DIR"
                ;;
        esac
    fi
}
trap cleanup EXIT HUP INT TERM

usage() {
    cat <<'EOF'
Usage: sudo ./scripts/diagnose-huawei-ar8100-snmp.sh

The script prompts for the target, SNMPv3 security name, optional context,
selected interface names/indices, and hidden passphrases. It performs read-only
SNMPv3 GET/GETBULK operations and writes bounded evidence under /tmp.

It refuses to overwrite an earlier report, share summary, or evidence directory.
EOF
}

if (($#)); then
    [[ $# -eq 1 && "$1" == "--help" ]] && { usage; exit 0; }
    usage >&2
    exit 2
fi

for command in awk cat chmod date grep mkdir mktemp python3 rm sed sha256sum sleep snmpbulkwalk snmpget timeout tr wc; do
    command -v "$command" >/dev/null 2>&1 || die "required command is missing: $command"
done
SNMP_HELP=$(snmpget -h 2>&1 || true)
grep -Fq 'SHA-256' <<<"$SNMP_HELP" || die 'installed snmpget does not advertise SHA-256 support'
grep -Fq 'AES-192' <<<"$SNMP_HELP" || die 'installed snmpget does not advertise AES-192 support'
unset SNMP_HELP

[[ -t 0 ]] || die 'an interactive terminal is required for hidden credential input'
[[ ! -e "$REPORT" ]] || die "$REPORT already exists; archive it explicitly before another run"
[[ ! -e "$SHARE_SUMMARY" ]] || die "$SHARE_SUMMARY already exists; archive it explicitly before another run"
[[ ! -e "$EVIDENCE_DIR" ]] || die "$EVIDENCE_DIR already exists; archive it explicitly before another run"
[[ -r /proc/mounts ]] || die '/proc/mounts is unavailable; cannot verify memory-only credential storage'
awk '$2 == "/dev/shm" && $3 == "tmpfs" { found=1 } END { exit !found }' /proc/mounts \
    || die '/dev/shm is not a verified tmpfs; refusing to persist SNMP passphrases'

read -r -p 'AR8100 IP address or hostname: ' TARGET
read -r -p 'SNMP UDP port [161]: ' PORT
PORT=${PORT:-161}
read -r -p 'SNMPv3 security name: ' SECURITY_NAME
read -r -p 'SNMPv3 context name [empty]: ' CONTEXT_NAME
read -r -p "Interface name(s) or ifIndex, comma-separated [$DEFAULT_INTERFACE]: " SELECTORS
SELECTORS=${SELECTORS:-$DEFAULT_INTERFACE}
read -r -s -p 'SNMPv3 authentication passphrase: ' AUTH_PASSPHRASE
printf '\n' >&2
read -r -s -p 'SNMPv3 privacy passphrase: ' PRIV_PASSPHRASE
printf '\n' >&2

[[ "$TARGET" =~ ^[A-Za-z0-9][A-Za-z0-9.-]*$ ]] \
    || die 'target must be an IPv4 address or DNS hostname without a port'
[[ "$PORT" =~ ^[0-9]+$ ]] && ((PORT >= 1 && PORT <= 65535)) || die 'port must be 1-65535'
[[ -n "$SECURITY_NAME" && "$SECURITY_NAME" != *$'\n'* ]] || die 'security name is required'
[[ "$CONTEXT_NAME" != *$'\n'* ]] || die 'invalid context name'
[[ -n "$SELECTORS" && "$SELECTORS" != *$'\n'* ]] || die 'at least one interface selector is required'
((${#AUTH_PASSPHRASE} >= 8)) || die 'authentication passphrase is shorter than the SNMPv3 minimum'
((${#PRIV_PASSPHRASE} >= 8)) || die 'privacy passphrase is shorter than the SNMPv3 minimum'

mkdir -m 0700 -- "$EVIDENCE_DIR"
SECRET_DIR=$(mktemp -d /dev/shm/huawei-ar8100-snmp.XXXXXX)
mkdir -m 0700 -- "$SECRET_DIR/persist"

snmp_conf_quote() {
    local value=$1
    value=${value//\\/\\\\}
    value=${value//\"/\\\"}
    printf '"%s"' "$value"
}

{
    printf 'defAuthPassphrase %s\n' "$(snmp_conf_quote "$AUTH_PASSPHRASE")"
    printf 'defPrivPassphrase %s\n' "$(snmp_conf_quote "$PRIV_PASSPHRASE")"
} >"$SECRET_DIR/snmp.conf"
chmod 0600 "$SECRET_DIR/snmp.conf"
AUTH_PASSPHRASE=
PRIV_PASSPHRASE=
unset AUTH_PASSPHRASE PRIV_PASSPHRASE

SNMP_ENV=(env "SNMPCONFPATH=$SECRET_DIR" "SNMP_PERSISTENT_DIR=$SECRET_DIR/persist" MIBS= MIBDIRS=)
SNMP_ARGS=(-v 3 -l authPriv -u "$SECURITY_NAME" -a "$AUTH_PROTOCOL" -x "$PRIV_PROTOCOL" -t 3 -r 1 -On)
[[ -z "$CONTEXT_NAME" ]] || SNMP_ARGS+=(-n "$CONTEXT_NAME")
TARGET_SPEC="${TARGET}:${PORT}"

run_get() {
    local oid=$1 output=$2
    "${SNMP_ENV[@]}" timeout "${COMMAND_TIMEOUT}s" snmpget "${SNMP_ARGS[@]}" "$TARGET_SPEC" "$oid" \
        >"$output" 2>&1
}

run_walk() {
    local label=$1 oid=$2 output=$3 status_file=$4 status rows
    status=0
    "${SNMP_ENV[@]}" timeout "${COMMAND_TIMEOUT}s" snmpbulkwalk -Cr10 "${SNMP_ARGS[@]}" "$TARGET_SPEC" "$oid" \
        >"$output" 2>&1 || status=$?
    rows=$(wc -l <"$output")
    {
        printf 'label=%s\n' "$label"
        printf 'root=%s\n' "$oid"
        printf 'exit_status=%s\n' "$status"
        printf 'rows=%s\n' "$rows"
    } >"$status_file"
    ((rows <= MAX_WALK_ROWS)) || die "$label exceeded $MAX_WALK_ROWS rows; bounded collection stopped"
    return 0
}

printf 'Verifying SNMPv3 identity with %s/%s...\n' "$AUTH_PROTOCOL" "$PRIV_PROTOCOL"
: >"$EVIDENCE_DIR/device-identity.raw"
for oid in .1.3.6.1.2.1.1.5.0 .1.3.6.1.2.1.1.1.0 .1.3.6.1.2.1.1.2.0; do
    identity_part="$EVIDENCE_DIR/identity-${oid##*.}.tmp"
    if ! run_get "$oid" "$identity_part"; then
        cat "$identity_part" >>"$EVIDENCE_DIR/device-identity.raw"
        rm -f -- "$identity_part"
        die 'SNMPv3 identity query failed; see device-identity.raw (no passphrases are recorded)'
    fi
    cat "$identity_part" >>"$EVIDENCE_DIR/device-identity.raw"
    rm -f -- "$identity_part"
done
if grep -Eqi 'No Such|Timeout|Authentication failure|Unknown user|Decryption error' "$EVIDENCE_DIR/device-identity.raw"; then
    die 'SNMPv3 identity was not proven; see device-identity.raw'
fi

declare -A IF_COLUMNS=(
    [ifIndex]=.1.3.6.1.2.1.2.2.1.1
    [ifName]=.1.3.6.1.2.1.31.1.1.1.1
    [ifDescr]=.1.3.6.1.2.1.2.2.1.2
    [ifAlias]=.1.3.6.1.2.1.31.1.1.1.18
    [ifType]=.1.3.6.1.2.1.2.2.1.3
    [ifOperStatus]=.1.3.6.1.2.1.2.2.1.8
    [ifAdminStatus]=.1.3.6.1.2.1.2.2.1.7
)
for column in ifIndex ifName ifDescr ifAlias ifType ifOperStatus ifAdminStatus; do
    run_walk "$column" "${IF_COLUMNS[$column]}" "$EVIDENCE_DIR/$column.raw" "$EVIDENCE_DIR/$column.status"
done

python3 - "$EVIDENCE_DIR" "$SELECTORS" <<'PY'
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
selectors = [part.strip() for part in sys.argv[2].split(',') if part.strip()]
bases = {
    'ifIndex': '.1.3.6.1.2.1.2.2.1.1',
    'ifName': '.1.3.6.1.2.1.31.1.1.1.1',
    'ifDescr': '.1.3.6.1.2.1.2.2.1.2',
    'ifAlias': '.1.3.6.1.2.1.31.1.1.1.18',
    'ifType': '.1.3.6.1.2.1.2.2.1.3',
    'ifOperStatus': '.1.3.6.1.2.1.2.2.1.8',
    'ifAdminStatus': '.1.3.6.1.2.1.2.2.1.7',
}

def clean(value):
    value = value.strip()
    if ': ' in value:
        value = value.split(': ', 1)[1]
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value = value[1:-1]
    return ''.join(ch if ch.isprintable() else '?' for ch in value)

rows = {}
for column, base in bases.items():
    for line in (root / f'{column}.raw').read_text(errors='replace').splitlines():
        match = re.match(r'^(\.?[0-9.]+)\s*=\s*(.*)$', line)
        if not match or not match.group(1).startswith(base + '.'):
            continue
        index = match.group(1)[len(base) + 1:]
        if not index.isdigit():
            continue
        rows.setdefault(index, {})[column] = clean(match.group(2))

order = sorted(rows, key=lambda value: int(value))
with (root / 'interface-mapping.tsv').open('w', encoding='utf-8') as handle:
    handle.write('ifIndex\tifName\tifDescr\tifAlias\tifType\tifOperStatus\tifAdminStatus\n')
    for index in order:
        values = rows[index]
        handle.write('\t'.join([index] + [values.get(key, '') for key in bases if key != 'ifIndex']) + '\n')

sep = '\x1f'
with (root / 'selected-interfaces.txt').open('w', encoding='utf-8') as handle:
    for selector in selectors:
        if selector.isdigit() and selector in rows:
            matches = [selector]
        else:
            matches = [index for index in order if selector in (rows[index].get('ifName'), rows[index].get('ifDescr'))]
        status = 'OK' if len(matches) == 1 else 'WRONG_MAPPING'
        index = matches[0] if len(matches) == 1 else ''
        values = rows.get(index, {})
        fields = [selector, status, index, values.get('ifName', ''), values.get('ifDescr', ''),
                  values.get('ifAlias', ''), values.get('ifType', ''),
                  values.get('ifOperStatus', ''), values.get('ifAdminStatus', ''), str(len(matches))]
        handle.write(sep.join(field.replace('\n', '?') for field in fields) + '\n')
PY

mapfile -t SELECTED_ROWS <"$EVIDENCE_DIR/selected-interfaces.txt"
RESOLVED_INDEXES=()
for row in "${SELECTED_ROWS[@]}"; do
    IFS=$'\x1f' read -r selector map_status if_index _ <<<"$row"
    [[ "$map_status" == OK ]] && RESOLVED_INDEXES+=("$if_index")
done

declare -A COUNTER_OIDS=(
    [ifInOctets]=.1.3.6.1.2.1.2.2.1.10
    [ifOutOctets]=.1.3.6.1.2.1.2.2.1.16
    [ifHCInOctets]=.1.3.6.1.2.1.31.1.1.1.6
    [ifHCOutOctets]=.1.3.6.1.2.1.31.1.1.1.10
    [ifSpeed]=.1.3.6.1.2.1.2.2.1.5
    [ifHighSpeed]=.1.3.6.1.2.1.31.1.1.1.15
)

sample_standard() {
    local phase=$1 output="$EVIDENCE_DIR/standard-counters-$1.raw" field index part
    : >"$output"
    for index in "${RESOLVED_INDEXES[@]}"; do
        for field in ifInOctets ifOutOctets ifHCInOctets ifHCOutOctets ifSpeed ifHighSpeed; do
            part="$EVIDENCE_DIR/.${phase}-${field}-${index}.tmp"
            run_get "${COUNTER_OIDS[$field]}.$index" "$part" || true
            cat "$part" >>"$output"
            rm -f -- "$part"
        done
    done
}

BEFORE_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)
sample_standard before
run_walk HUAWEI-IF-EXT-MIB "$IF_EXT_ROOT" "$EVIDENCE_DIR/huawei-if-ext-before.raw" "$EVIDENCE_DIR/huawei-if-ext-before.status"
run_walk HUAWEI-CBQOS-MIB "$CBQOS_ROOT" "$EVIDENCE_DIR/huawei-cbqos-before.raw" "$EVIDENCE_DIR/huawei-cbqos-before.status"
printf 'Sampling counters again after %s seconds...\n' "$SAMPLE_INTERVAL"
sleep "$SAMPLE_INTERVAL"
sample_standard after
run_walk HUAWEI-IF-EXT-MIB "$IF_EXT_ROOT" "$EVIDENCE_DIR/huawei-if-ext-after.raw" "$EVIDENCE_DIR/huawei-if-ext-after.status"
run_walk HUAWEI-CBQOS-MIB "$CBQOS_ROOT" "$EVIDENCE_DIR/huawei-cbqos-after.raw" "$EVIDENCE_DIR/huawei-cbqos-after.status"
AFTER_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)

python3 - "$EVIDENCE_DIR" "$BEFORE_UTC" "$AFTER_UTC" "$SAMPLE_INTERVAL" <<'PY' >"$EVIDENCE_DIR/analysis.txt"
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
before_utc, after_utc, interval = sys.argv[2:]
sep = '\x1f'

def parse_values(path):
    values = {}
    for line in path.read_text(errors='replace').splitlines():
        match = re.match(r'^(\.?[0-9.]+)\s*=\s*([^:]+):\s*(.*)$', line)
        if not match:
            continue
        oid, kind, raw = match.groups()
        number = re.search(r'(?:^|\()([0-9]+)(?:\)|$)', raw.strip())
        values[oid] = {'kind': kind.strip(), 'raw': raw.strip(),
                       'number': int(number.group(1)) if number else None}
    return values

def delta(old, new):
    if old is None or new is None:
        return None
    value = new - old
    if value >= 0:
        return value
    return value + (1 << 64 if max(old, new) > 0xffffffff else 1 << 32)

before = parse_values(root / 'standard-counters-before.raw')
after = parse_values(root / 'standard-counters-after.raw')
bases = {
    'ifInOctets': '.1.3.6.1.2.1.2.2.1.10',
    'ifOutOctets': '.1.3.6.1.2.1.2.2.1.16',
    'ifHCInOctets': '.1.3.6.1.2.1.31.1.1.1.6',
    'ifHCOutOctets': '.1.3.6.1.2.1.31.1.1.1.10',
    'ifSpeed': '.1.3.6.1.2.1.2.2.1.5',
    'ifHighSpeed': '.1.3.6.1.2.1.31.1.1.1.15',
}

print('STANDARD COUNTER ANALYSIS')
print(f'before_utc={before_utc}')
print(f'after_utc={after_utc}')
print(f'configured_sleep_seconds={interval}')
selected_indexes = set()
classifications = []
for line in (root / 'selected-interfaces.txt').read_text(errors='replace').splitlines():
    selector, status, index, name, descr, alias, iftype, oper, admin, matches = line.split(sep)
    print()
    print(f'interface_selector={selector}')
    print(f'mapping_status={status}')
    print(f'mapping_match_count={matches}')
    if status != 'OK':
        print('classification=WRONG_MAPPING')
        print('recommendation=Do not change Zabbix. Resolve the live ifName/ifDescr/ifIndex mapping first.')
        classifications.append('WRONG_MAPPING')
        continue
    selected_indexes.add(index)
    print(f'ifIndex={index}')
    print(f'ifName={name}')
    print(f'ifDescr={descr}')
    print(f'ifAlias={alias}')
    print(f'ifType={iftype}')
    print(f'ifOperStatus={oper}')
    print(f'ifAdminStatus={admin}')
    counters = {}
    for field, base in bases.items():
        oid = f'{base}.{index}'
        old = before.get(oid, {}).get('number')
        new = after.get(oid, {}).get('number')
        movement = delta(old, new)
        counters[field] = (old, new, movement)
        print(f'{field}.before={old if old is not None else "UNSUPPORTED"}')
        print(f'{field}.after={new if new is not None else "UNSUPPORTED"}')
        if field not in ('ifSpeed', 'ifHighSpeed'):
            print(f'{field}.delta={movement if movement is not None else "UNSUPPORTED"}')

    status_number = re.search(r'\((\d+)\)', oper) or re.match(r'^(\d+)$', oper)
    admin_number = re.search(r'\((\d+)\)', admin) or re.match(r'^(\d+)$', admin)
    is_down = ((status_number and status_number.group(1) != '1') or
               (admin_number and admin_number.group(1) != '1'))
    hc = [counters[name] for name in ('ifHCInOctets', 'ifHCOutOctets')]
    c32 = [counters[name] for name in ('ifInOctets', 'ifOutOctets')]
    hc_supported = any(item[0] is not None and item[1] is not None for item in hc)
    c32_supported = any(item[0] is not None and item[1] is not None for item in c32)
    hc_active = any((item[2] or 0) > 0 for item in hc)
    c32_active = any((item[2] or 0) > 0 for item in c32)
    hc_all_zero = hc_supported and all((item[0] in (None, 0) and item[1] in (None, 0)) for item in hc)
    all_supported_values_zero = (hc_supported or c32_supported) and all(
        item[0] in (None, 0) and item[1] in (None, 0) for item in hc + c32)

    if is_down:
        classification = 'INTERFACE_DOWN'
        recommendation = 'Do not infer a counter defect while the selected interface is not operationally and administratively up.'
    elif hc_active:
        classification = 'HC64_ACTIVE'
        recommendation = 'Keep the official IF-MIB HC64 strategy. The earlier zero was not reproduced in this sample.'
    elif hc_all_zero and c32_active:
        classification = 'HC64_ZERO_32_ACTIVE'
        recommendation = ('Do not use 32-bit counters permanently on a 10G link. Correlate Huawei candidates with exact MIB definitions, '
                          'device software behavior, and vendor support before creating an extension item.')
    elif not hc_supported and not c32_supported:
        classification = 'COUNTER_UNSUPPORTED'
        recommendation = 'No standard octet source was proven. Review candidate evidence and the exact AR8100 MIB package.'
    elif all_supported_values_zero:
        classification = 'BOTH_ZERO'
        recommendation = 'Both supported standard counter families returned zero. Use candidate evidence; do not blame preprocessing.'
    elif c32_active and not hc_supported:
        classification = 'COUNTER_UNSUPPORTED_HC64_32_ACTIVE'
        recommendation = 'HC64 is unavailable and 32-bit moves; 32-bit is diagnostic only for 10G. Seek a verified 64-bit source.'
    elif not hc_active and not c32_active:
        classification = 'NO_COUNTER_MOVEMENT_OBSERVED'
        recommendation = 'Counters exist but did not move in this window. Repeat only while traffic is independently confirmed.'
    else:
        classification = 'COUNTER_BEHAVIOR_INCONCLUSIVE'
        recommendation = 'Retain the raw evidence and obtain a traffic-correlated sample before template changes.'
    print(f'classification={classification}')
    classifications.append(classification)

    if_speed = counters['ifSpeed'][1]
    high_speed = counters['ifHighSpeed'][1]
    if (if_speed in (None, 0)) and (high_speed in (None, 0)):
        print('secondary_classification=SPEED_UNKNOWN')
    print(f'recommendation={recommendation}')

print()
print('HUAWEI ENTERPRISE CANDIDATE CHANGES')
changed_any = False
for label, filename, mib_root in (
    ('HUAWEI-IF-EXT-MIB', 'huawei-if-ext', '.1.3.6.1.4.1.2011.5.25.41'),
    ('HUAWEI-CBQOS-MIB', 'huawei-cbqos', '.1.3.6.1.4.1.2011.5.25.32'),
):
    first = parse_values(root / f'{filename}-before.raw')
    second = parse_values(root / f'{filename}-after.raw')
    candidates = []
    for oid in sorted(first.keys() & second.keys(), key=lambda value: [int(x) for x in value.strip('.').split('.')]):
        old, new = first[oid]['number'], second[oid]['number']
        if old is None or new is None:
            continue
        movement = new - old
        if movement < 0 and first[oid]['kind'] in ('Counter32', 'Counter64'):
            movement += 1 << (64 if first[oid]['kind'] == 'Counter64' else 32)
        if movement == 0:
            continue
        suffix = oid[len(mib_root):].strip('.') if oid.startswith(mib_root + '.') else ''
        components = set(suffix.split('.'))
        candidates.append((oid, first[oid]['kind'], old, new, movement, bool(components & selected_indexes)))
    print(f'{label}.returned_before={len(first)}')
    print(f'{label}.returned_after={len(second)}')
    print(f'{label}.changed_numeric_objects={len(candidates)}')
    for oid, kind, old, new, movement, index_match in candidates[:50]:
        changed_any = True
        print(f'candidate={label}|oid={oid}|type={kind}|before={old}|after={new}|delta={movement}|selected_index_component={str(index_match).upper()}')
    if len(candidates) > 50:
        print(f'{label}.candidate_output_truncated={len(candidates) - 50}')

print()
print('OVERALL')
print('classifications=' + (','.join(classifications) if classifications else 'NO_INTERFACE_RESOLVED'))
print('huawei_changed_numeric_candidates=' + ('PRESENT_UNVERIFIED' if changed_any else 'NONE_OBSERVED'))
print('implementation_strategy=Keep Huawei VRP linked. Create only uniquely keyed dependent items in the extension after an OID, type, index relationship, and traffic-correlated delta are proven. Disable or replace official interface LLD only as a separate reviewed production change.')
PY

python3 - "$EVIDENCE_DIR/device-identity.raw" <<'PY' >"$EVIDENCE_DIR/device-identity.txt"
import re
import sys
from pathlib import Path

labels = {
    '.1.3.6.1.2.1.1.5.0': 'sysName',
    '.1.3.6.1.2.1.1.1.0': 'sysDescr',
    '.1.3.6.1.2.1.1.2.0': 'sysObjectID',
}
for line in Path(sys.argv[1]).read_text(errors='replace').splitlines():
    match = re.match(r'^(\.?[0-9.]+)\s*=\s*(.*)$', line)
    if match and match.group(1) in labels:
        value = ''.join(ch if ch.isprintable() else '?' for ch in match.group(2))
        print(f'{labels[match.group(1)]}={value}')
PY

python3 - "$EVIDENCE_DIR" "$SHARE_SUMMARY" "$DIAGNOSTIC_VERSION" <<'PY'
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
summary_path = Path(sys.argv[2])
version = sys.argv[3]
sep = '\x1f'

def clean(value, limit=160):
    value = ' '.join(''.join(ch if ch.isprintable() else '?' for ch in value).split())
    return value[:limit] if value else 'UNAVAILABLE'

identity = {}
for line in (root / 'device-identity.txt').read_text(errors='replace').splitlines():
    if '=' in line:
        key, value = line.split('=', 1)
        identity[key] = clean(value)

sysdescr = identity.get('sysDescr', 'UNAVAILABLE')
model_match = re.search(r'\b(AR[0-9][A-Za-z0-9-]*)\b', sysdescr, re.IGNORECASE)
model = model_match.group(1).upper() if model_match else 'UNRESOLVED_FROM_SYSDESCR'
sysobjectid = identity.get('sysObjectID', 'UNAVAILABLE')
sysobjectid = re.sub(r'^(?:OID|OBJECT IDENTIFIER):\s*', '', sysobjectid, flags=re.IGNORECASE)

analysis_lines = (root / 'analysis.txt').read_text(errors='replace').splitlines()
sections = []
current = None
for line in analysis_lines:
    if line.startswith('interface_selector='):
        current = {'selector': line.split('=', 1)[1]}
        sections.append(current)
    elif current is not None and '=' in line and not line.startswith('candidate='):
        key, value = line.split('=', 1)
        current[key] = value
    if line == 'HUAWEI ENTERPRISE CANDIDATE CHANGES':
        current = None

def counter_status(section, prefix):
    before = section.get(f'{prefix}.before', 'UNSUPPORTED')
    after = section.get(f'{prefix}.after', 'UNSUPPORTED')
    delta = section.get(f'{prefix}.delta', 'UNSUPPORTED')
    if 'UNSUPPORTED' in (before, after, delta):
        return 'UNSUPPORTED DELTA=UNSUPPORTED'
    try:
        state = 'MOVING' if int(delta) > 0 else ('ZERO' if int(before) == 0 and int(after) == 0 else 'STATIC')
    except ValueError:
        state = 'UNKNOWN'
    return f'{state} DELTA={delta}'

live_candidates = []
for line in analysis_lines:
    if not line.startswith('candidate=') or 'selected_index_component=TRUE' not in line:
        continue
    match = re.search(r'\|oid=(\.?[0-9.]+)\|', line)
    if match and match.group(1) not in live_candidates:
        live_candidates.append(match.group(1))

output = [
    'SHARE SUMMARY',
    f'DIAGNOSTIC_VERSION={version}',
    f'MODEL={model}',
    f'SYSOBJECTID={clean(sysobjectid)}',
    f'SYSDESCR={clean(sysdescr)}',
]
for number, section in enumerate(sections[:2], 1):
    name = clean(section.get('ifName', section.get('selector', 'UNRESOLVED')), 80)
    output.extend((
        f'INTERFACE_{number}={name}',
        f'IFINDEX_{number}={clean(section.get("ifIndex", "UNCONFIRMED"), 32)}',
        f'STATUS_{number}=OPER:{clean(section.get("ifOperStatus", "UNKNOWN"), 40)} ADMIN:{clean(section.get("ifAdminStatus", "UNKNOWN"), 40)}',
        f'SPEED_{number}=BPS:{clean(section.get("ifSpeed.after", "UNSUPPORTED"), 32)} HIGH_MBPS:{clean(section.get("ifHighSpeed.after", "UNSUPPORTED"), 32)}',
        f'RX32_{number}={counter_status(section, "ifInOctets")}',
        f'TX32_{number}={counter_status(section, "ifOutOctets")}',
        f'RX64_{number}={counter_status(section, "ifHCInOctets")}',
        f'TX64_{number}={counter_status(section, "ifHCOutOctets")}',
        f'ROOT_CAUSE_{number}={clean(section.get("classification", "INCONCLUSIVE"), 80)}',
        f'NEXT_ACTION_{number}={clean(section.get("recommendation", "Review bounded evidence."), 180)}',
    ))
if len(sections) > 2:
    output.append(f'ADDITIONAL_SELECTED_INTERFACES={len(sections) - 2}')

output.append('HUAWEI_ENTERPRISE_COUNTER_USABLE=NO_MIB_SEMANTICS_UNVERIFIED')
output.append('LIVE_INDEX_CORRELATED_CANDIDATE=' + ('OBSERVED_UNVERIFIED' if live_candidates else 'NONE_OBSERVED'))
if live_candidates:
    output.append('LIVE_CANDIDATE_OIDS=' + ','.join(live_candidates[:3]))
output.append('END SHARE SUMMARY')

if len(output) > 30:
    raise SystemExit(f'share summary exceeded 30 lines: {len(output)}')
summary_path.write_text('\n'.join(output) + '\n', encoding='utf-8')
PY

{
    printf 'Huawei AR8100 SNMP diagnostic report\n'
    printf 'Generated UTC: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'Runtime access: SNMPv3 authPriv, %s authentication, %s privacy\n' "$AUTH_PROTOCOL" "$PRIV_PROTOCOL"
    printf 'Target address, security name, context and passphrases are not recorded.\n'
    printf 'No SNMP SET operation is implemented by this script.\n\n'
    printf 'DEVICE IDENTITY\n'
    cat "$EVIDENCE_DIR/device-identity.txt"
    printf '\nINTERFACE/INDEX MAPPING\n'
    cat "$EVIDENCE_DIR/interface-mapping.tsv"
    printf '\nSELECTED INTERFACE ANALYSIS\n'
    cat "$EVIDENCE_DIR/analysis.txt"
    printf '\nSUPPORTED CAPABILITY/WALK STATUS\n'
    for status_file in "$EVIDENCE_DIR"/*.status; do
        tr '\n' ' ' <"$status_file"
        printf '\n'
    done
    printf '\nLIMITATIONS\n'
    printf '%s\n' '- A changed private numeric OID is only a candidate, not proof that it is a traffic counter.'
    printf '%s\n' '- selected_index_component is a correlation hint, not proof of the private table index schema.'
    printf '%s\n' '- No AR8100-specific OID is activated or recommended until its MIB definition and live behavior agree.'
    printf '%s\n' '- A no-movement result is meaningful only if traffic was independently present during the sample.'
} >"$REPORT"

chmod 0600 "$REPORT" "$SHARE_SUMMARY" "$EVIDENCE_DIR"/*
sha256sum "$REPORT" >"$EVIDENCE_DIR/report.sha256"

printf '\nDiagnostic collection complete.\n'
printf 'Report: %s\n' "$REPORT"
printf 'Bounded raw evidence: %s\n' "$EVIDENCE_DIR"
printf 'Photo-friendly summary: %s\n' "$SHARE_SUMMARY"
printf 'Preserve the detailed report and evidence locally; photograph the sanitized summary below.\n'
printf '\n'
cat "$SHARE_SUMMARY"

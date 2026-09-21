# Huawei AR8100 interface-counter diagnostic

Status: offline preparation only. No Huawei device exists in the lab, no
production access was available, and no runtime validation against an AR8100
has been performed. Every device-specific conclusion remains **UNVERIFIED**
until an operator runs the diagnostic in production and returns its output.

## What is already known

The production operator has established that SNMPv3 authPriv communication,
the SNMP user, and the firewall path work; Zabbix discovers interfaces; and
`10GE0/0/5` was mapped to ifIndex 10 by both `ifDescr.10` and `ifName.10`.
Huawei CLI traffic was approximately 20 Mbps. The official template requested
`IF-MIB::ifHCInOctets.10` (`1.3.6.1.2.1.31.1.1.1.6.10`), and Zabbix Test Item
returned a raw value of zero before preprocessing. That evidence does not point
to a dashboard or Change-per-second calculation fault. It also does not prove
why the agent returned zero or that ifIndex 10 is still current tomorrow.

## Source findings

The official Zabbix 7.0 `Huawei VRP by SNMP` template discovers interface
identity/status from IF-MIB with `discovery[]`. Its interface traffic
prototypes use `get[]` against `ifHCInOctets` and `ifHCOutOctets`, then apply
Change per second and multiply octets by eight. Speed uses `ifHighSpeed`.
This exactly explains the observed production request; it does not prove the
AR8100 populates those objects correctly.

The newer official `Huawei AR600 by SNMP` template is present in newer upstream
branches and is explicitly scoped to the AR600 Series. It demonstrates the
Zabbix `walk[]` master-item, SNMP walk-to-JSON, and dependent-item pattern. Its
network-interface walk uses standard IF-MIB 32-bit `ifInOctets`/`ifOutOctets`
and `ifSpeed`. It also uses Huawei private MIB families for other features.
AR600 behavior is not evidence of AR8100 behavior, and its 32-bit interface
strategy is not suitable as a permanent assumption for a 10 Gbit/s link.

Zabbix 7.0 supports native SNMP `walk[OID1,...]` items as master items and the
SNMP walk-to-JSON / SNMP walk-value preprocessing steps. This is the preferred
future shape if live AR8100 evidence identifies a stable table: one bounded
walk, dependent discovery, and uniquely keyed dependent items.

As of this research, the current official upstream network-template tree has
Huawei VRP and Huawei AR600 templates, but no AR8000/AR8100-specific template.
Huawei publishes a model/release-specific MIB reference and MIB Query tool for
AR5700/AR6700/AR8000, including AR8100-family models. The exact deployed model,
VRP release, MIB objects, syntax, and index definitions must be checked against
that product release. The diagnostic therefore probes these families without
assuming an object exists:

- IF-MIB `ifTable` and `ifXTable`: authoritative standard mapping, status,
  speed, and 32-/64-bit counter comparison.
- HUAWEI-IF-EXT-MIB under `1.3.6.1.4.1.2011.5.25.41`: a Huawei-documented
  interface-management family on Huawei platforms; AR8100 availability and
  semantics remain unverified.
- HUAWEI-CBQOS-MIB under `1.3.6.1.4.1.2011.5.25.32`: used by the official
  AR600 template for QoS counters; AR8100 availability and relevance to total
  physical-interface traffic remain unverified.

The script does not walk the whole `1.3.6.1.4.1.2011` enterprise tree and does
not embed a guessed private counter OID.

Authoritative references reviewed:

- [Zabbix 7.0 Huawei VRP template source](https://git.zabbix.com/projects/ZBX/repos/zabbix/browse/templates/net/huawei_snmp/template_net_huawei_snmp.yaml?at=release%2F7.0)
- [Zabbix Huawei AR600 template source](https://git.zabbix.com/projects/ZBX/repos/zabbix/browse/templates/net/huawei_ar600_snmp/template_net_huawei_ar600_snmp.yaml?at=release%2F7.4)
- [Zabbix 7.0 SNMP item documentation](https://www.zabbix.com/documentation/7.0/en/manual/config/items/itemtypes/snmp)
- [Zabbix 7.0 SNMP walk LLD documentation](https://www.zabbix.com/documentation/7.0/en/manual/discovery/low_level_discovery/examples/snmp_oids_walk)
- [Zabbix 7.0 template linking and host-level customization](https://www.zabbix.com/documentation/7.0/en/manual/config/templates/linking)
- [Huawei AR5700/AR6700/AR8000 V600R024C10 MIB Reference](https://info.support.huawei.com/enterprise/en/doc/EDOC1100459924/a48652bd/huawei-tunnel-mib)
- [Huawei AR8100-family model MIB Query entry](https://info.support.huawei.com/info-finder/search-center/en/enterprise/Routers/AR814012G10XG-supported-Optical-Module-pid-251332536/mib)
- [Net-SNMP command security options](https://www.net-snmp.org/docs/man/snmpcmd.html)

## Open hypotheses

The diagnostic distinguishes these possibilities without selecting one in
advance:

- the current interface-to-ifIndex mapping differs from the earlier test;
- the interface is down or the sample has no traffic;
- IF-MIB 64-bit counters work and the earlier zero was transient/contextual;
- IF-MIB 64-bit counters stay zero while 32-bit counters increment;
- standard counters are unsupported or static and a documented Huawei table
  may expose a usable counter;
- no candidate can be proven in one sample, requiring the exact Huawei MIB
  package, a traffic-correlated repeat, or a vendor case.

## What the script does

`scripts/diagnose-huawei-ar8100-snmp.sh` performs only SNMPv3 GET and GETBULK
operations. It has no SNMP SET path. It verifies `sysName`, `sysDescr`, and
`sysObjectID`; walks seven standard interface columns; resolves selected names
or indices; samples IF-MIB 32- and 64-bit octet counters and both speed objects
twice; and compares bounded Huawei IF-EXT and CBQOS subtrees across the same
window.

Each command has a timeout, walks use a low max-repetitions value, each walk is
limited to 10,000 rows, and a 16 MiB per-file process limit is enforced. Raw
evidence is saved rather than dumped to the terminal. Existing output is never
overwritten.

Passphrases are read with hidden terminal input. They are not command-line
arguments, environment variables, reports, or `/tmp` evidence. During the run,
Net-SNMP reads them from a mode-0600 configuration inside verified `/dev/shm`
tmpfs; the directory is removed on exit. The script refuses to run if it cannot
prove `/dev/shm` is tmpfs. The target address, security name, and context are
also omitted from the report. Device identity and interface descriptions are
included because they are required evidence; review them for site sensitivity
before transfer.

Required commands are `snmpget`, `snmpbulkwalk`, `timeout`, Python 3, and basic
RHEL utilities. Missing commands cause a clear failure. The script does not
install anything and needs no external network access. Before asking for
credentials, it also requires the installed `snmpget` help to advertise both
SHA-256 and AES-192; it does not weaken the requested protocols to make a test
run.

## Run tomorrow

From the fresh repository checkout on the isolated Zabbix server, run exactly:

```bash
sudo ./scripts/diagnose-huawei-ar8100-snmp.sh
```

At the prompts, enter the AR8100 address, UDP port (normally 161), existing
SNMPv3 security name, optional context, and interface selector(s). Accept the
default `10GE0/0/5` only if that remains the intended live interface. Enter the
existing SHA-256 authentication and AES192 privacy passphrases at the hidden
prompts. Generate independently confirmed traffic during the sampling window;
the script does not generate traffic.

It writes:

- `/tmp/huawei-ar8100-diagnostic-report.txt`
- `/tmp/huawei-ar8100-share-summary.txt`, a sanitized 20-30 line maximum
  summary that is also printed last for photographing with a phone
- `/tmp/huawei-ar8100-diagnostic/` with bounded raw SNMP output, status files,
  parsed mapping, analysis, and report SHA-256.

If either path already exists, the script stops. Archive it deliberately and
rerun; do not make the script destroy old evidence.

To display only the compact summary again:

```bash
sudo cat /tmp/huawei-ar8100-share-summary.txt
```

The summary omits the target, SNMP security name, passphrases, and raw walks.
It lists a private numeric candidate only when that OID was actually returned
by the live device, changed during the sample, and contained a selected
ifIndex component. That remains correlation evidence, not proof of MIB
semantics or a usable replacement counter.

## Result interpretation

- `HC64_ACTIVE`: IF-MIB 64-bit counters moved. Keep the official HC64 approach;
  do not add a private OID merely because one also changed.
- `HC64_ZERO_32_ACTIVE`: 64-bit values remained zero while 32-bit counters
  moved. This proves a behavioral split for the sample, not a permanent 32-bit
  solution. A 32-bit counter can wrap rapidly at 10 Gbit/s.
- `BOTH_ZERO`: supported standard counters returned zero at both samples. This
  supports the raw-counter observation but not its cause.
- `COUNTER_UNSUPPORTED` or `COUNTER_UNSUPPORTED_HC64_32_ACTIVE`: one or both
  standard families were not returned. Preserve exact Net-SNMP errors.
- `WRONG_MAPPING`: the requested name/index was absent or ambiguous. Correct
  mapping is required before any counter conclusion.
- `INTERFACE_DOWN`: counter behavior is not classified as a monitoring defect
  while the interface is not administratively and operationally up.
- `SPEED_UNKNOWN`: neither speed object produced a usable nonzero value. This
  is secondary to the counter classification.
- `NO_COUNTER_MOVEMENT_OBSERVED`: counters exist but did not move. It is not a
  fault finding unless real traffic was independently present.
- `PRESENT_UNVERIFIED` Huawei candidates: a numeric private object changed.
  The full numeric OID, ASN.1 type, exact model/release MIB definition, table
  indexes, direction, units, monotonicity, wrap/reset behavior, and correlation
  with known traffic must all be proven before implementation. An OID suffix
  containing the selected ifIndex is only a hint.

## Future extension and official-template coexistence

Keep `Huawei VRP by SNMP` linked for its device-health items. Any extension
must use distinct keys and should use a bounded `walk[]` master item with
dependent LLD/items only after live proof. Do not duplicate official item keys.

Zabbix permits inherited entities, including discovery rules, to be disabled
at the host level. Therefore a reviewed future migration can disable the
inherited `Network interfaces discovery` for the AR8100 host while keeping the
official template linked, preserving its unrelated health/entity rules. The
extension would then need complete replacement coverage for every interface
signal still required. A more selective host-level disable of individual
inherited traffic prototypes is also possible, but later template updates can
override host customizations. Neither action is part of this package, and
existing discovered items/lost-resource behavior must be reviewed before any
production change.

`templates/huawei_ar8100_extensions_by_snmp.yaml` is intentionally empty. It
does not contain unresolved OIDs as active or disabled items and is not ready
to link.

## Evidence gate before Zabbix changes

Keep the full report and raw directory on the isolated server for local review.
If local archival is useful, create it with:

```bash
sudo tar --owner=0 --group=0 -C /tmp -czf /tmp/huawei-ar8100-diagnostic.tgz \
  huawei-ar8100-diagnostic-report.txt huawei-ar8100-diagnostic
```

The archive contains the two standard-counter samples, interface-column walks,
Huawei subtree before/after walks and status files, parsed mapping, analysis,
and checksum. It is not required to leave the isolated production network.
Photograph only the compact share summary and separately state whether
independently observed traffic was present throughout the sampling interval.
Do not send passphrases; the package cannot contain them.

Only after that evidence proves an object should the extension define an item.
The evidence must establish OID, ASN.1 counter type, index mapping, direction,
units, monotonic delta under traffic, behavior at idle, and reset/discontinuity
handling. Until then the root cause and remediation remain unproven.

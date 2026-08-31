# SPEC-04 — Lab Tests

## Four estates

1. **REAL** — existing Proxmox host, LXCs, VMs, and services for genuine metrics
   and failures. Do not create fake Linux servers merely to populate Zabbix.
2. **MOCK DCIM** — NetBox-only, clearly tagged/tenanted, monitoring disabled,
   used for racks, cabling, power, circuits, and portal behavior.
3. **EMULATED NETWORK** — existing PNETLab/EVE when available; genuine emulated
   appliances may be NetBox devices but have no fictional rack positions/media.
4. **SNMP/LLDP SIMULATOR** — optional later LXC replaying legitimately obtained,
   sanitized recordings; it is test infrastructure, not an estate device.

## Required real tests

Verify Proxmox monitoring, guest discovery, LXC/QEMU representation as NetBox
virtual machines, NetBox service monitoring, application reachability, resource
metrics, and controlled real failure behavior. Existing workloads may not be
changed without explicit approval and a rollback plan.

## Mock DCIM and cabling

Fixtures must cover direct cable; switch -> panel front/rear -> trunk -> remote
rear/front -> server; broken/incomplete path; LAG members; A/B power; circuit
termination; planned and inter-rack cables; front/rear devices; 0U PDU; and an
unracked device. Traversal must resolve the far operational endpoint to the
server NIC rather than the first patch-panel termination.

## Observed topology

Keep intended L1, observed LLDP/CDP, virtualization, logical service, and Zabbix
attributes separate with provenance and timestamps. Test `MATCH`, `MISMATCH`,
`MISSING`, `DISCOVERED`, `UNKNOWN`, `STALE`, and `IGNORED`; stale never equals
mismatch. Vendor fixtures must test local-port normalization without assuming
LLDP local port number equals ifIndex.

## Negative and clean-room tests

Test unavailable NetBox/Zabbix, invalid or insufficient credentials, stale LLDP,
duplicate names/PKs across types, ambiguous management IP, excessive change
budget, forbidden delete/unlink attempts, signature/hash failures, dependency or
module metadata gaps, missing corporate values, lab leakage, rerun convergence,
restore, and fresh disconnected RHEL installation.

## Status and evidence

Every result is `PASS`, `FAIL`, `NOT-EXECUTED`, or `NOT-APPLICABLE` per SPEC-00.
Evidence must identify the command/procedure, time, target, expected result,
observed result, and sanitized raw evidence path. Never infer success.

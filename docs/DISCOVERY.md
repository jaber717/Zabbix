# Milestone 0 Discovery

Evidence captured 2026-09-01. Raw files under `evidence/discovery/raw/` are the
authoritative source for later decisions. If a required fact is absent, stop and
request it rather than inferring it from this report or memory.

## Verified facts

| Fact | Classification | Evidence |
|---|---|---|
| Current execution host is Windows NT 10.0.19045.0 x64 with PowerShell, OpenSSH, and Git 2.55.0. | VERIFIED FACT | `raw/local-capability.txt` |
| Outbound HTTPS reached official Zabbix and Red Hat sites with HTTP 200. | VERIFIED FACT | `raw/internet-capability.txt` |
| Proxmox host `JaberLAB` is reachable through non-interactive SSH and runs `pve-manager/8.4.13` with kernel `6.8.12-14-pve`. | VERIFIED FACT | `raw/proxmox-read-only.txt` |
| QEMU 110 PNET4.2.4, 120 EVE-LAB, 130 Ansible, and 140 Netbox existed and were stopped at capture time. | VERIFIED FACT | `raw/proxmox-read-only.txt` |
| LXCs 200–205, 211, 212, and 9000 existed and were running; 210 and 9001 existed and were stopped at capture time. | VERIFIED FACT | `raw/proxmox-read-only.txt` |
| LXC 9000 is running, named `netbox-demo`, unprivileged, Ubuntu/amd64, DHCP on `vmbr0`, and held `192.168.1.89/24` at capture time. | VERIFIED FACT | `raw/netbox-read-only.txt` |
| NetBox `manage.py version` reported 6.0.8. Core NetBox, worker, nginx, PostgreSQL, and Redis services returned active. | VERIFIED FACT | `raw/netbox-read-only.txt` |
| Direct unauthenticated `/api/` returned HTTP 403. The existing topology portal successfully used a credential through a GET/HEAD-only client. | VERIFIED FACT | `raw/netbox-read-only.txt`, `raw/portal-source-inventory.txt` |
| The read-only portal view observed 3 sites, 4 locations, 11 racks, 81 devices, 84 cables, 2 circuits, 43 prefixes, and 116 IP addresses. | VERIFIED FACT | `raw/netbox-read-only.txt` |
| Direct read-only endpoint audit observed 81 devices (active/planned), 10 roles, 4 platforms, 8 manufacturers, and 40 devices with a primary IP. | VERIFIED FACT | `raw/netbox-read-only.txt` |
| The existing credential was insufficient for virtual machines, tags, and custom fields. | VERIFIED FACT | `raw/netbox-read-only.txt` |
| A local topology portal source tree is present and exposes read-only graph/summary routes; it was not detected as its own Git repository. | VERIFIED FACT | `raw/portal-source-inventory.txt` |
| The build VM became reachable at `192.168.1.91`; public-key SSH authenticated as unprivileged user `jaber`, and `hostname -f` returned `netbox-dev`. | VERIFIED FACT | `raw/rhel-build-baseline.txt` |
| The build VM runs Red Hat Enterprise Linux 9.6 (Plow), x86_64, kernel `5.14.0-570.12.1.el9_6.x86_64`, under KVM/QEMU. The `redhat-release` package is `9.6-0.1.el9.x86_64`. | VERIFIED FACT | `raw/rhel-build-baseline.txt`, `raw/rhel-build-repository-readiness.txt` |
| A single `sudo -n true` check succeeded. Subsequent privileged read-only queries reported subscription-manager Overall Status `Disabled`, Simple Content Access mode, a successful identity response (identifiers redacted), and release `9.6`. | VERIFIED FACT | `raw/rhel-build-repository-readiness.txt` |
| `subscription-manager repos --list-enabled` reported no repositories matching the criteria. Current `dnf repolist` showed only `netbox-offline-base` and `netbox-offline-modules`. | VERIFIED FACT | `raw/rhel-build-repository-readiness.txt` |
| `dnf repolist --all` listed standard RHEL 9 BaseOS/AppStream definitions, including `rhel-9-for-x86_64-baseos-rpms` and `rhel-9-for-x86_64-appstream-rpms`, as disabled. This proves current state only, not permanent entitlement or availability. | VERIFIED FACT | `raw/rhel-build-repository-readiness.txt` |
| Current offline modular metadata exposed PostgreSQL 15 and 16 (16 marked enabled), PHP 8.1/8.2/8.3, and nginx 1.22/1.24/1.26 (1.24 marked enabled). No stream was changed. | VERIFIED FACT | `raw/rhel-build-baseline.txt` |
| Installed `python3` reports 3.9.21. The available `python3*` query against the currently enabled repositories exposed Python 3.9.21 packages; this does not establish all Python versions available from restored Red Hat sources. | VERIFIED FACT | `raw/rhel-build-baseline.txt` |
| The VM has an 80 GiB disk; `/` had 46 GiB available and `/home` had 23 GiB available at capture time. | VERIFIED FACT | `raw/rhel-build-baseline.txt` |

Runtime statuses, addresses, counts, and reachability are point-in-time facts, not
permanent configuration guarantees.

## Architect baselines

These are approved inputs from the project architecture, not results of this
discovery:

- ARCHITECT BASELINE: Zabbix 7.0.30 LTS, last architect verification 31 August
  2026.
- ARCHITECT BASELINE: target RHEL 9.6 x86_64.
- ARCHITECT BASELINE: PostgreSQL 16 candidate.
- ARCHITECT BASELINE: future Zabbix VM is separate from NetBox, with SELinux
  Enforcing and firewalld enabled.
- ARCHITECT BASELINE: NetBox LXC 9000 is the integration source; QEMU 140 is not.

Internet reachability was verified, but no upstream version verification report
was performed and the approved Zabbix baseline was not changed.

## Assumptions

- ASSUMPTION: the existing portal credential is intentionally scoped to the
  portal's DCIM use case. Its permission design was not changed or independently
  audited beyond observed endpoint outcomes.
- ASSUMPTION: the local portal source corresponds closely to the running portal;
  observed route/version behavior supports this, but no deployed-source checksum
  comparison was executed.

Assumptions are not build inputs until verified.

## Unknowns

- UNKNOWN: BaseOS/AppStream entitlement and actual usability from the future
  clean build context. They are currently disabled/not enabled; this does not
  prove permanent unavailability.
- UNKNOWN: required Zabbix and other approved source-repository readiness for M1.
- UNKNOWN: approved Python minor/ABI for the integration service. Python 3.9.21
  is observed in the current offline-repository view but has not been selected.
- UNKNOWN: NetBox VM inventory, VM statuses/primary IP coverage, monitoring-related
  tags, and monitoring-related custom fields because the available credential was
  denied.
- UNKNOWN: PNETLab/EVE guest versions and management reachability; both guests
  were stopped and deliberately not started.
- UNKNOWN: exact Zabbix/RHEL package availability and modular metadata behavior;
  no build was authorized.
- UNKNOWN: whether the current topology portal is functionally compatible with
  NetBox 6.0.8 beyond the limited successful GETs observed.

## Blockers and contradictions

| Item | Gate impact |
|---|---|
| RHEL source repository readiness | BLOCKER FOR M1 |
| NetBox VM/tag/custom-field read permission | BLOCKER FOR M4 |
| NetBox 6.0.8 versus portal 4.6.9 | BLOCKS/AFFECTS M4 and M6 |
| PNETLab/EVE stopped | Prerequisite only for M8; not an M1 blocker |

### NetBox and portal version mismatch

- EXPECTED: Existing portal documentation/runtime declaration identifies NetBox
  4.6.9.
- ACTUAL: NetBox `manage.py version` reports 6.0.8 while portal health and source
  still report a hardcoded 4.6.9.
- IMPACT: Version-sensitive portal and future integration behavior cannot use the
  portal label as authoritative. NetBox 6.0 API compatibility and any migration
  effects require explicit validation.
- RECOMMENDATION: Treat 6.0.8 as the current verified NetBox runtime version,
  revalidate the portal against it in a separately authorized non-mutating test,
  and later replace hardcoded version reporting with a verified runtime value.

### Required integration reads are denied

- EXPECTED: Future integration discovery must inspect devices and virtual
  machines and evaluate monitoring-related tags/custom fields.
- ACTUAL: Devices are readable; VM, tag, and custom-field endpoints were denied
  through the available read-only credential.
- IMPACT: A device-only design would violate the architecture, and eligibility
  mapping cannot be approved from current evidence.
- RECOMMENDATION: In a later authorized step, provision or approve a read-only
  credential with the listed view permissions. Do not alter NetBox permissions in
  Milestone 0.

### RHEL source repository readiness

- EXPECTED: The RHEL 9.6 build context can use verified BaseOS, AppStream, and all
  other approved source repositories needed for clean installroot dependency
  resolution.
- ACTUAL: The VM shell is reachable and its OS/storage/module facts were captured.
  DNF currently enables only the pre-existing NetBox offline repositories;
  BaseOS/AppStream definitions are visible but disabled, and subscription-manager
  lists no enabled repositories.
- IMPACT: Existing offline content cannot be treated as authoritative source
  closure for Zabbix. BaseOS/AppStream entitlement and clean-build usability have
  not been verified, so M1 remains blocked.
- RECOMMENDATION: Have the system/subscription owner restore or verify the approved
  source repositories outside this discovery run, then repeat the non-mutating
  readiness checks in `evidence/discovery/REQUIRED-EVIDENCE.md` before M1 approval.

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
| The generic Django `manage.py version` command returned 6.0.8. M4 later proved this is the Django version; NetBox `/api/status/`, API headers, install path, and portal health identify NetBox 4.6.9/API 4.6. Core services were active. | VERIFIED FACT, CORRECTED CLASSIFICATION | `raw/netbox-read-only.txt`, `evidence/m4/raw/netbox-api-preflight.txt`, `evidence/m4/raw/netbox-version-reconciliation.txt` |
| Direct unauthenticated `/api/` returned HTTP 403. The existing topology portal successfully used a credential through a GET/HEAD-only client. | VERIFIED FACT | `raw/netbox-read-only.txt`, `raw/portal-source-inventory.txt` |
| The read-only portal view observed 3 sites, 4 locations, 11 racks, 81 devices, 84 cables, 2 circuits, 43 prefixes, and 116 IP addresses. | VERIFIED FACT | `raw/netbox-read-only.txt` |
| Direct read-only endpoint audit observed 81 devices (active/planned), 10 roles, 4 platforms, 8 manufacturers, and 40 devices with a primary IP. | VERIFIED FACT | `raw/netbox-read-only.txt` |
| The existing credential was initially insufficient for virtual machines, virtual-machine interfaces, tags, and custom fields. M4 preserved those HTTP 403 results; its 2026-09-02 resumption later verified HTTP 200 for all four. | VERIFIED HISTORICAL FACT, LATER RESOLVED | `raw/netbox-read-only.txt`, `evidence/m4/raw/netbox-api-preflight.txt`, `evidence/m4/resume-pass/raw/permission-revalidation.txt` |
| A local topology portal source tree is present and exposes read-only graph/summary routes; it was not detected as its own Git repository. | VERIFIED FACT | `raw/portal-source-inventory.txt` |
| The build VM became reachable at `192.168.1.91`; public-key SSH authenticated as unprivileged user `jaber`, and `hostname -f` returned `netbox-dev`. | VERIFIED FACT | `raw/rhel-build-baseline.txt` |
| The build VM runs Red Hat Enterprise Linux 9.6 (Plow), x86_64, kernel `5.14.0-570.12.1.el9_6.x86_64`, under KVM/QEMU. The `redhat-release` package is `9.6-0.1.el9.x86_64`. | VERIFIED FACT | `raw/rhel-build-baseline.txt`, `raw/rhel-build-repository-readiness.txt` |
| A single `sudo -n true` check succeeded. Subsequent privileged read-only queries reported subscription-manager Overall Status `Disabled`, Simple Content Access mode, a successful identity response (identifiers redacted), and release `9.6`. | VERIFIED FACT | `raw/rhel-build-repository-readiness.txt` |
| Before M0.5, `subscription-manager repos --list-enabled` reported no repositories matching the criteria and `dnf repolist` showed only `netbox-offline-base` and `netbox-offline-modules`. | VERIFIED FACT | `raw/rhel-build-repository-readiness.txt` |
| Before M0.5, `dnf repolist --all` listed standard RHEL 9 BaseOS/AppStream definitions, including `rhel-9-for-x86_64-baseos-rpms` and `rhel-9-for-x86_64-appstream-rpms`, as disabled. | VERIFIED FACT | `raw/rhel-build-repository-readiness.txt` |
| Current offline modular metadata exposed PostgreSQL 15 and 16 (16 marked enabled), PHP 8.1/8.2/8.3, and nginx 1.22/1.24/1.26 (1.24 marked enabled). No stream was changed. | VERIFIED FACT | `raw/rhel-build-baseline.txt` |
| Installed `python3` reports 3.9.21. The available `python3*` query against the currently enabled repositories exposed Python 3.9.21 packages; this does not establish all Python versions available from restored Red Hat sources. | VERIFIED FACT | `raw/rhel-build-baseline.txt` |
| The VM has an 80 GiB disk; `/` had 46 GiB available and `/home` had 23 GiB available at capture time. | VERIFIED FACT | `raw/rhel-build-baseline.txt` |

## M0.5 verified source readiness

- VERIFIED FACT: The live Red Hat inventory confirmed the standard repository IDs
  `rhel-9-for-x86_64-baseos-rpms` and
  `rhel-9-for-x86_64-appstream-rpms` before enablement.
- VERIFIED FACT: M0.5 enabled only those two Red Hat repositories. The pre-existing
  `netbox-offline-base` and `netbox-offline-modules` repositories were retained
  unchanged. The release pin remained 9.6.
- VERIFIED FACT: With every other repository disabled, BaseOS/AppStream metadata
  refresh and a `bash` package query succeeded. Real RHEL sources exposed
  PostgreSQL streams 15/16, PHP 8.1/8.2/8.3, nginx 1.22/1.24/1.26, and Python
  package families for minors 3.9, 3.11, and 3.12.
- VERIFIED FACT: Official Zabbix 7.0 RHEL 9 x86_64 repository metadata was
  reachable at `https://repo.zabbix.com/zabbix/7.0/rhel/9/x86_64/`. Query-only
  metadata contained exact `7.0.30-release1.el9` packages for all investigated
  server, web, Agent 2, tool, web-service, and proxy families.
- VERIFIED FACT: The official key file was reachable and GPG reported fingerprint
  `4C3D 6F2C C75F 5146 754F C374 D913 219A B533 3005`. RPM signature verification
  was not performed because no RPM payload was downloaded; that remains an M1
  build gate.
- VERIFIED FACT: A disposable RHEL 9.6/x86_64 installroot with an empty RPM
  database saw only BaseOS, AppStream, and a temporary official Zabbix repository.
  Exact Zabbix 7.0.30 core packages and recursive dependencies resolved only from
  those three sources. RPM counts stayed zero, no RPM payload was downloaded,
  host RPM/module-state hashes were unchanged, SELinux remained Enforcing, and
  the validated temporary root was removed.

The clean installroot printed an expected subscription-plugin warning because the
disposable root contained no consumer identity. It nevertheless accessed the
explicit host-approved Red Hat repository definitions and completed all metadata
and resolution queries successfully. This warning is not evidence that the host
registration is invalid.

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

M0.5 verified the approved exact Zabbix 7.0.30 package set in the official RHEL 9
repository. It did not perform a general newer-upstream version review and did not
change the approved baseline.

## Assumptions

- ASSUMPTION: the existing portal credential is intentionally scoped to the
  portal's DCIM use case. Its permission design was not changed or independently
  audited beyond observed endpoint outcomes.
- ASSUMPTION: the local portal source corresponds closely to the running portal;
  observed route/version behavior supports this, but no deployed-source checksum
  comparison was executed.

Assumptions are not build inputs until verified.

## Unknowns

- UNKNOWN: approved Python minor/ABI for the integration service. Approved RHEL
  sources expose 3.9, 3.11, and 3.12 package families, but M0.5 did not select one.
- RESOLVED AFTER M0: M4 read 0 VMs, 0 VM interfaces, 0 tags, and 1 custom field;
  all 81 devices were deterministically not opted in. See
  `evidence/m4/resume-pass/PLAN-REVIEW.md`.
- UNKNOWN: PNETLab/EVE guest versions and management reachability; both guests
  were stopped and deliberately not started.
- UNKNOWN: complete M1 dependency closure, RPM signature results, and offline
  modular-metadata reproduction. M0.5 proved source readiness only and did not
  build or download the artifact payload.
- UNKNOWN: portal feature behavior beyond the limited successful GETs. The
  supposed 6.0.8-versus-4.6.9 version contradiction is resolved; NetBox and the
  portal both report NetBox 4.6.9, while Django is 6.0.8.

## Blockers and contradictions

| Item | Gate impact |
|---|---|
| RHEL source repository readiness | RESOLVED; M1 source gate READY |
| NetBox VM/VM-interface/tag/custom-field read permission | RESOLVED; all four reads pass and M4 is COMPLETE |
| NetBox/Django/portal version classification | RESOLVED by M4: NetBox 4.6.9, API 4.6, Django 6.0.8 |
| PNETLab/EVE stopped | Prerequisite only for M8; not an M1 blocker |

### NetBox and portal version classification — resolved by M4

- EXPECTED: Existing portal documentation/runtime declaration identifies NetBox
  4.6.9.
- ACTUAL: M4's authenticated `/api/status/` labels NetBox as 4.6.9, Django as
  6.0.8, and the API header as 4.6. `/opt/netbox` resolves to
  `/opt/netbox-4.6.9`; portal health also reports NetBox 4.6.9. The generic
  `manage.py version` output was Django's version.
- IMPACT: There is no NetBox 6.0 migration or version blocker for M4. Portal
  feature validation remains future M6 work, but not because of a live version
  mismatch.
- RECOMMENDATION: Use authenticated NetBox status/API fields for product version
  evidence and label framework versions separately.

### Required integration reads — resolved by M4

- EXPECTED: Future integration discovery must inspect devices and virtual
  machines and evaluate monitoring-related tags/custom fields.
- ACTUAL: The original and first resumed checks returned HTTP 403 and remain
  preserved. On 2026-09-02 the same installed credential for principal
  `topology-portal` returned HTTP 200 for all four resources. Full candidate
  collection and explicit reconciliation gates then passed.
- IMPACT: The M4 permission blocker is resolved without granting NetBox write
  actions. M4 is accepted; M5 is ready but not started.
- RECOMMENDATION: Retain the four view actions and existing empty constraints;
  do not add NetBox add/change/delete/sync permissions.

### RHEL source repository readiness — resolved by M0.5

- EXPECTED: The RHEL 9.6 build context can use verified BaseOS, AppStream, and all
  other approved source repositories needed for clean installroot dependency
  resolution.
- ACTUAL: BaseOS and AppStream were enabled through subscription-manager, queried
  independently, and used with the temporary official Zabbix 7.0 source in an
  isolated clean installroot. The NetBox offline repositories had zero influence.
- IMPACT: The source-readiness blocker for M1 is resolved. Full dependency
  download, RPM signature verification, module metadata preservation, artifact
  assembly, and Python selection remain M1 work rather than M0.5 work.
- RECOMMENDATION: M1 may begin after explicit approval, using the exact source IDs,
  release pin, architecture, isolation pattern, and evidence recorded here.

# Project Status

## Current gate

Milestone: **M1 — Offline Build Pipeline**

State: **COMPLETE**

Milestone baseline commit: `62ba3275a3f016b2f07d333684286b59c1188cfa`

M0.5 source-readiness commit: `b2180c00d0a6029a65996055ae7becbcddc5f0b7`

M0.5 source readiness and M1 are complete. The first M1 transaction stopped at
the missing-`fping` dependency gate. After the owner approved the official
Zabbix non-supported RHEL 9 x86_64 source for only the pinned `fping` RPM, two
fresh clean builds completed without EPEL or any broader source expansion.
M2 has not been started; its gate is ready for separate explicit authorization.

M1 pipeline source commit: `fbf3573`

M1 blocked-run evidence commit: `499f35a`

M1 fping source-policy commit: `c6dedeb`

M1 accepted build source commit: `91947c3`

## Gate and blocker matrix

| Item | Current evidence | Gate impact |
|---|---|---|
| RHEL source repository readiness | BaseOS/AppStream and official Zabbix 7.0 sources passed host and isolated clean-installroot metadata/query tests. | RESOLVED; M1 COMPLETE |
| `fping` source for Zabbix Server | The non-supported source contributed only `fping-0:5.1-1.el9.x86_64`; repository metadata, SHA256, key fingerprint, signature, and provenance passed. | RESOLVED; M1 COMPLETE |
| NetBox VM/tag/custom-field permission | Existing read-only credential is denied for these endpoints. | BLOCKS M4 |
| NetBox/portal version mismatch | NetBox reports 6.0.8; portal declares 4.6.9. | BLOCKS/AFFECTS M4 and M6 |
| PNETLab/EVE stopped | QEMU 110 and 120 were stopped and left unchanged. | Prerequisite only for M8 |

See `docs/DISCOVERY.md` and `evidence/discovery/REQUIRED-EVIDENCE.md`.

## M1 result

- Build 1 and Build 2 each completed in a fresh empty RPM database with 313
  locked RPMs and zero wheels. Source counts are BaseOS 167, AppStream 132,
  official Zabbix 13, and non-supported `fping` 1.
- PostgreSQL 16, PHP 8.3, and nginx 1.24 module metadata was preserved. Local-only
  module enable, package resolution, main installation, and separate PostgreSQL
  and SQLite proxy installations passed with all external repositories disabled.
- Every RPM signature passed in an isolated trust database. The `fping` RPM is
  locked with its exact upstream repository, NEVRA, SHA256, and pinned official
  Zabbix signing-key fingerprint.
- The nine-case negative suite passed. Build 2 matched Build 1 for the lockfile,
  modular metadata, artifact allow-list, RPM checksums/provenance, and byte-level
  repository contents.
- Accepted artifact: `zabbix-rhel96-offline-1.0.0-build1.tar.gz`, 178093296 bytes,
  SHA256 `dbcd9a1185a21f1bc44bff356f06088ac63d77a5bb8fe539ad573280d9cef42b`.
- See `evidence/m1/ACCEPTANCE.md`, `evidence/m1/final-build1/raw/`, and
  `evidence/m1/final-build2/raw/`. The original stopped run remains under
  `evidence/m1/resolution/`.

## M0.5 acceptance

| Item | Status | Evidence |
|---|---|---|
| RHEL BaseOS repository ID confirmed | PASS | Live inventory contained `rhel-9-for-x86_64-baseos-rpms`. |
| RHEL AppStream repository ID confirmed | PASS | Live inventory contained `rhel-9-for-x86_64-appstream-rpms`. |
| BaseOS usable | PASS | Isolated makecache, `bash` query, and clean resolution succeeded. |
| AppStream usable | PASS | Isolated module/Python queries and clean resolution succeeded. |
| RHEL release remains pinned to 9.6 | PASS | Pre-change, post-change, and final clean-context queries returned 9.6. |
| Real RHEL module streams captured | PASS | PostgreSQL, PHP, and nginx inventories came from only BaseOS/AppStream. |
| Python availability captured from approved RHEL sources | PASS | Python 3.9, 3.11, and 3.12 package families were observed. |
| Official Zabbix RHEL 9 repository reachable | PASS | HTTPS repomd, key, makecache, and repoquery succeeded. |
| Zabbix 7.0.30 package families verified | PASS | All eleven investigated families returned `7.0.30-release1.el9`. |
| Clean installroot accesses approved sources | PASS | Attempt 4 used an empty RPM database and completed package/dependency queries. |
| NetBox offline repositories excluded | PASS | Clean repolist and resolved repo IDs contained only BaseOS, AppStream, and `m05-zabbix`. |
| No host packages installed/updated | PASS | No install/update command ran; host RPM hash matched and clean RPM count stayed zero. |
| No module state changed | PASS | Module-state aggregate hashes matched before/after. |
| No secrets committed | PASS | Staged-content scans found no private-key marker, credential-like literal, or unredacted subscription identity. |
| Build source evidence committed | PASS | Commit `b2180c00d0a6029a65996055ae7becbcddc5f0b7`. |

## M0 acceptance

| Item | Status | Evidence |
|---|---|---|
| Hard constraints captured | PASS | `docs/SPEC-00-CONSTRAINTS.md` reviewed. |
| Six SPEC documents created | PASS | `docs/SPEC-00` through `SPEC-05` exist. |
| Capability check completed | PASS | `evidence/discovery/CAPABILITIES.md`. |
| Live discovery only where access was proven | PASS | Batch-mode SSH was proven before `pve*`/`pct` reads; NetBox calls used GET/HEAD-only client. |
| No fabricated facts | PASS | Report distinguishes verified facts, baselines, assumptions, unknowns, and blockers with evidence paths. |
| Raw evidence stored | PASS | Eight sanitized transcripts/inventories under `evidence/discovery/raw/`, including Build VM baseline and full repository-readiness output. |
| Missing evidence explicitly requested | PASS | `evidence/discovery/REQUIRED-EVIDENCE.md`. |
| NetBox LXC 9000 was not modified | PASS | Only selected config/status/version and HTTP GET reads were executed; no write endpoint or modifying command was called. |
| Existing Proxmox workloads were not modified | PASS | `hostname`, `uname`, `pveversion`, `pvesh get`, `qm list`, `pct list/config/exec` with read-only inner commands only. |
| No secrets committed | PASS | Staged and committed content scans found no private-key marker or credential-like literal assignment. |
| `DISCOVERY.md` created | PASS | `docs/DISCOVERY.md`. |
| `PLAN.md` created | PASS | `PLAN.md` includes scope, inputs, deliverables, tests, permissions, risks, and stop for M0–M9. |
| `PROJECT-STATUS.md` updated | PASS | This file records gate and blockers. |
| Git status reviewed | PASS | `git diff --cached --check` returned 0 before commit; post-commit `git status --short` was empty. |
| Milestone commit created | PASS | `62ba3275a3f016b2f07d333684286b59c1188cfa` on branch `main`. |
| Build VM network and authenticated shell | PASS | TCP/22 opened and key-only SSH reached `192.168.1.91` as `jaber`; remote hostname was `netbox-dev`. |
| Build VM OS/module/Python/storage discovery | PASS | Requested non-mutating commands executed; see `rhel-build-baseline.txt`. |
| Privileged subscription read | PASS | The one `sudo -n true` check succeeded; authorized read-only subscription commands then returned evidence. |
| BaseOS/AppStream clean-build usability | NOT-EXECUTED | Current definitions are disabled and only prior offline repos are enabled. Preconditions: owner-restored approved sources and an authorized clean-context readiness test. Expected evidence: usable BaseOS/AppStream and required source IDs without relying on prior offline content. |

## Safety statement

- NetBox modified: **No**.
- Proxmox configuration or guest lifecycle modified: **No**.
- Build VM repository state modified: **Yes, authorized** — only standard RHEL 9
  BaseOS and AppStream were enabled.
- RHEL packages installed/updated/removed in M1: **Yes, authorized build tooling
  only** — `createrepo_c`, `modulemd-tools`,
  `python3-dnf-plugin-modulesync`, and three direct libraries. No general update
  ran. PostgreSQL 16/nginx 1.24 packages were already present before the M1 tool
  transaction; no Zabbix package is installed on the host.
- Module state, release pin, SELinux policy/mode, firewall, or networking modified:
  **No**.
- DNF metadata cache changed: **Yes, expected** from authorized `makecache` tests.
- Persistently enabled repositories after M1: **Unchanged by M1** — BaseOS,
  AppStream, and the two pre-existing NetBox offline repositories are visible.
  No temporary M1/Zabbix repository definition file exists; every build
  transaction disabled all global repositories before enabling its exact source
  set, so the NetBox repositories had zero build influence.
- Secrets placed in evidence or documentation: **No observed occurrence**; M0
  staged-content scans found no private-key marker or credential-like literal.
- M1 disposable roots: **Removed** after each accepted build; final active-root
  inventory was empty.
- M1 host package/module hashes: **Unchanged during both accepted builds after
  the authorized tool transaction**; final host Zabbix package inventory was
  empty.
- M1 output disk use at closeout: **1.5 GiB** under the remote build output
  directory; `/home` retained **21 GiB free** and `/` retained **46 GiB free**.

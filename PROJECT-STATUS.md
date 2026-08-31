# Project Status

## Current gate

Milestone: **M0 — Discovery + Specifications**

State: **COMPLETE**

Milestone baseline commit: `62ba3275a3f016b2f07d333684286b59c1188cfa`

No M1 work is authorized. Build-VM shell discovery is complete, but M1 remains
blocked until source-repository readiness is verified and explicit approval is
given.

## Gate and blocker matrix

| Item | Current evidence | Gate impact |
|---|---|---|
| RHEL source repository readiness | VM and SSH are available. Current DNF view enables only pre-existing NetBox offline repositories; BaseOS/AppStream and required build sources are not verified usable from a clean build context. | BLOCKS M1 |
| NetBox VM/tag/custom-field permission | Existing read-only credential is denied for these endpoints. | BLOCKS M4 |
| NetBox/portal version mismatch | NetBox reports 6.0.8; portal declares 4.6.9. | BLOCKS/AFFECTS M4 and M6 |
| PNETLab/EVE stopped | QEMU 110 and 120 were stopped and left unchanged. | Prerequisite only for M8 |

See `docs/DISCOVERY.md` and `evidence/discovery/REQUIRED-EVIDENCE.md`.

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
- Proxmox guests modified: **No**.
- RHEL packages, repositories, subscription configuration, module state, SELinux,
  firewall, and networking modified: **No**.
- Secrets placed in evidence or documentation: **No observed occurrence**; M0
  staged-content scans found no private-key marker or credential-like literal.

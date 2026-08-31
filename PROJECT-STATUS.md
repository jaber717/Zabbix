# Project Status

## Current gate

Milestone: **M0 — Discovery + Specifications**

State: **COMPLETE pending recorded Git commit verification**

No M1 work is authorized. The next gate is M1 only after explicit approval and
after required RHEL evidence and architecture-affecting blockers are resolved.

## Blockers

1. RHEL build VM is unreachable; module streams, Python ABI, enabled repositories,
   subscription status, and disk remain unknown.
2. NetBox reports 6.0.8 while the running/local portal declares 4.6.9.
3. Available read-only NetBox credential lacks VM, tag, and custom-field view
   permissions required by the approved integration scope.

See `docs/DISCOVERY.md` and `evidence/discovery/REQUIRED-EVIDENCE.md`.

## M0 acceptance

| Item | Status | Evidence |
|---|---|---|
| Hard constraints captured | PASS | `docs/SPEC-00-CONSTRAINTS.md` reviewed. |
| Six SPEC documents created | PASS | `docs/SPEC-00` through `SPEC-05` exist. |
| Capability check completed | PASS | `evidence/discovery/CAPABILITIES.md`. |
| Live discovery only where access was proven | PASS | Batch-mode SSH was proven before `pve*`/`pct` reads; NetBox calls used GET/HEAD-only client. |
| No fabricated facts | PASS | Report distinguishes verified facts, baselines, assumptions, unknowns, and blockers with evidence paths. |
| Raw evidence stored | PASS | Six sanitized transcripts/inventories under `evidence/discovery/raw/`. |
| Missing evidence explicitly requested | PASS | `evidence/discovery/REQUIRED-EVIDENCE.md`. |
| NetBox LXC 9000 was not modified | PASS | Only selected config/status/version and HTTP GET reads were executed; no write endpoint or modifying command was called. |
| Existing Proxmox workloads were not modified | PASS | `hostname`, `uname`, `pveversion`, `pvesh get`, `qm list`, `pct list/config/exec` with read-only inner commands only. |
| No secrets committed | NOT-EXECUTED | Final staged-content secret scan and commit review occur after repository assembly. |
| `DISCOVERY.md` created | PASS | `docs/DISCOVERY.md`. |
| `PLAN.md` created | PASS | `PLAN.md` includes scope, inputs, deliverables, tests, permissions, risks, and stop for M0–M9. |
| `PROJECT-STATUS.md` updated | PASS | This file records gate and blockers. |
| Git status reviewed | NOT-EXECUTED | Scheduled after repository initialization/staging. |
| Milestone commit created | NOT-EXECUTED | Scheduled after final validation. |

## Safety statement

- NetBox modified: **No**.
- Proxmox guests modified: **No**.
- Secrets placed in evidence or documentation: **No observed occurrence**; final
  repository scan remains an M0 closeout test.

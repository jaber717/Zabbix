# NETOPS Hardware Health - release candidate 0.3.1-rc2

**Status: v0.3.1-rc2 - the five defects that got v0.3.0-rc1 rejected (Codex NO-GO, `5529012`) are fixed; independent re-acceptance is pending.** Engineering verdict: RELEASE CANDIDATE for independent LAB re-acceptance. NOT production-ready: real-device validation, a live template import and live delivery acceptance are outstanding (see `KNOWN-LIMITATIONS.md`). Template management design: `TEMPLATE-MANAGEMENT-DESIGN.md`; evidence: `ACCEPTANCE-V0.3.1-EVIDENCE.md`.

Branch `claude/hardware-health-v0.3.1-rc2`, built on the rejected candidate `c1f96cb` (v0.3.0-rc1, branch `claude/hardware-health-v0.3-rc`, left untouched). The exact tip SHA is given in the delivery message (a commit cannot contain its own hash).

## What is complete
| Area | Delivered |
|---|---|
| Engine (Phase 1) | Vendor definitions (`vendors/*.yaml`) -> generated Zabbix 7.0 templates: SNMP walk + dependent LLD + item/trigger prototypes (PAN-OS via HTTP agent), vendor value maps, confirm/recover sample protection, separate `sensor_stale` monitoring-quality trigger, unsupported sensors recorded with reasons, routing tags, no thresholds invented |
| Verification | `importcheck` (structure/uuid/expression/valuemap/tags/recovery/secret macro), `simulate` (generated expressions run against normal, fault, glitch, recovery, flap, wrong-state, stale series), 442 unit tests |
| LAB integration (Phase 2) | `labsim` read-only verification of the existing sim objects + notification isolation (fail-closed), print-only tag plan and exact restore plan, read-only event/alert evidence collector. The existing objects are never created, modified or re-tagged by the tool |
| Telegram (Phase 3) | Message contract (Problem/Recovery fields, 4096 limit) checked from the real action templates; routing table; preflight/execution/verification/emergency-disable/rollback in `TELEGRAM-RUNBOOK.md`; action stays disabled, validation file all `false` |
| Vendors (Phase 4) | Cisco IOS-XE, Cisco Nexus, Fortinet FortiGate, Huawei VRP, Palo Alto PAN-OS definitions with sources; ASR 8500 and FortiProxy recorded as BLOCKED. Four evidence levels in `VENDOR-COVERAGE.md` |
| Release (Phase 5) | Offline package (`build-package.sh`), `install.sh`, `upgrade.sh` (pre-upgrade backup), `rollback.sh`, `verify-deployment.sh`, `validate-lab.sh`; manifest + checksum verification; lifecycle tests; operator, install, runbook, limitations, self-review and acceptance documents |

## Evidence levels today
| Level | Cells (of 38 vendor x category cells) |
|---|---|
| REAL DEVICE VERIFIED | 0 |
| SIMULATED TESTED | 11 |
| IMPLEMENTED only | 0 |
| UNVERIFIED / BLOCKED | 27 |

## External blockers (cannot be removed by engineering)
1. **Real devices** of each vendor/platform, and an authorized window to poll them (L1, L7-L10).
2. **Operator approval** + independent security gate before the Hardware action may be enabled or any Telegram message sent (L4).
3. **Live import of the generated templates** into Zabbix 7.0.30 (L3): a LAB write, available through the guarded `template apply`, awaiting Codex/operator.
4. **Documentation for ASR 8500 / FortiProxy** (or devices) to define their sensors (L8).
5. Production: isolated/offline by design; install package is ready, access deliberately not attempted.

## Compatibility
Zabbix 7.0.30 export format 7.0; LAB Python 3.12 (suite run there); library syntax gated to the 3.8 grammar; PyYAML `>=6.0,<7.0`.

# NETOPS Hardware Health (independent project)

**Status: release candidate 0.3.1-rc2 (LAB). 442 offline tests. v0.3.0-rc1 was rejected by Codex for five template-management defects; all five are fixed (docs/ACCEPTANCE-V0.3.1-EVIDENCE.md). NOT production-ready: no real device has been polled, generated templates are not yet imported into a live Zabbix, Telegram delivery is NOT tested and the Hardware action is disabled.** See [docs/RELEASE-CANDIDATE.md](docs/RELEASE-CANDIDATE.md).

Separate from the frozen `zabbix-alerting` v1.0.2 interface project (unchanged by this work).

## Mandatory scope: four vendors

| Vendor | Platforms |
| --- | --- |
| Cisco | ASR 8500 / IOS-XR; Nexus / NX-OS; IOS / IOS-XE |
| Palo Alto Networks | PA-Series / PAN-OS |
| Fortinet | FortiGate; FortiProxy where present |
| Huawei | S-series / VRP switches; AR8140 |

Per family: fan, power, temperature, hardware redundancy and (where it exists) HA, each as **PASS / GAP / N/A with evidence / BLOCKED** - see [docs/COVERAGE-MATRIX.md](docs/COVERAGE-MATRIX.md) (today: 0 PASS, 4 GAP, 31 BLOCKED, 0 N/A). F5 is deferred.

## Commands

```bash
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -t .                                    # offline suite, no Zabbix needed

export ZABBIX_HARDWARE_URL_LAB=... ZABBIX_HARDWARE_TOKEN_LAB=...              # per-environment; never the same for LAB and Production
python3 hardware_audit.py --env lab discover --host NAME [--host NAME2]      # raw inputs vs concrete candidates, real values/timestamps/units/OIDs/model (never coverage)
python3 hardware_audit.py --env lab audit --output report.json                # verify what config/hardware.lab.yaml declares (exit 0 / 2 / 3)
python3 hardware_audit.py matrix --observations docs/observations/lab-discovery-2026-10-09.yaml --report report.json --out matrix.md
python3 hardware_audit.py --env lab action plan|apply|rollback               # the separate NETOPS-HW action (LAB only, created DISABLED)
```

### v0.3 additions

```bash
python3 hardware_audit.py vendors list|coverage|simulate|messages|check        # offline: definitions, 4-level coverage matrix, scenario simulation, Telegram message contract
python3 hardware_audit.py template build|check --definition cisco-iosxe        # offline: generate / validate the NETOPS-HW template
python3 hardware_audit.py --env lab template plan|apply|rollback --definition D # guarded, LAB only, never links to a host
python3 hardware_audit.py --env lab labsim [--evidence-since EPOCH]            # READ-ONLY check of the existing LAB simulator objects / their events and alerts
release/build-package.sh | install.sh | upgrade.sh | rollback.sh | verify-deployment.sh | validate-lab.sh   # offline package lifecycle
```

## Rules the tool enforces

* **Read-only audit.** Allowed API methods: `apiinfo.version`, `host.get`, `item.get`, `trigger.get`, `usermacro.get`, `action.get`, `usergroup.get`, `mediatype.get`. Only `action apply|rollback` opens a write client, limited to `action.create|update|delete`.
* **Server-side identity.** The Zabbix being queried must report `{$NETOPS.ENVIRONMENT}` equal to `--env`; a mismatch or a missing macro stops the run before any host is read. LAB and Production use different URLs, tokens and policy files; Production requires `zabbix.url_regex`.
* **No keyword coverage.** A sensor is covered only if the approved policy declares its exact item key and live Zabbix shows a concrete (non-raw-walk), enabled, supported, fresh item whose value is interpretable through a **verified** vendor mapping, with an enabled trigger bound to that item carrying `netops_hardware=1` and the matching `hardware_component`.
* **No invented vendor data.** Status meanings come from `vendors/*.yaml` (each cites its MIB object / pinned official template) and are marked DOCUMENTATION-DERIVED, NOT DEVICE-VERIFIED; `config/status-semantics.yaml` (operator additions) ships empty. A mapping is never reused across vendors.
* **HA is not hardware redundancy.** Separate categories, separate sensors, separate triggers (Fortinet and Palo Alto HA vs fan/PSU redundancy).
* **Missing data is not a fault.** An unreachable device makes its sensors BLOCKED; nothing is inferred about fans or PSUs from an SNMP timeout.
* **Empty approved inventories.** `config/hardware.lab.yaml` and `config/hardware.production.yaml` are `hosts: {}` until a real model's sensors are verified.

## Documents

| | |
|---|---|
| [docs/TEMPLATE-MANAGEMENT-DESIGN.md](docs/TEMPLATE-MANAGEMENT-DESIGN.md), [docs/ACCEPTANCE-V0.3.1-EVIDENCE.md](docs/ACCEPTANCE-V0.3.1-EVIDENCE.md), [docs/VENDOR-SOURCES-REVIEW.md](docs/VENDOR-SOURCES-REVIEW.md) | template ownership / drift / rollback design, rc2 evidence, verified vendor sources |
| [docs/RELEASE-CANDIDATE.md](docs/RELEASE-CANDIDATE.md), [docs/HANDOFF-V0.3.md](docs/HANDOFF-V0.3.md) | the v0.3 candidate, blockers, verdict |
| [docs/VENDOR-COVERAGE.md](docs/VENDOR-COVERAGE.md) | generated vendor coverage matrix, four evidence levels |
| [docs/OPERATOR-GUIDE.md](docs/OPERATOR-GUIDE.md), [docs/INSTALL-UPGRADE-ROLLBACK.md](docs/INSTALL-UPGRADE-ROLLBACK.md), [docs/TELEGRAM-RUNBOOK.md](docs/TELEGRAM-RUNBOOK.md) | operation |
| [docs/KNOWN-LIMITATIONS.md](docs/KNOWN-LIMITATIONS.md), [docs/SELF-REVIEW.md](docs/SELF-REVIEW.md), [docs/CODEX-ACCEPTANCE-CHECKLIST.md](docs/CODEX-ACCEPTANCE-CHECKLIST.md) | limits, review, acceptance |
| [docs/AUDIT-CORRECTIONS.md](docs/AUDIT-CORRECTIONS.md) | defect -> fix -> regression test |
| [docs/COVERAGE-MATRIX.md](docs/COVERAGE-MATRIX.md) | four-vendor matrix from the 2026-10-09 discovery |
| [docs/VENDOR-GAPS-AND-TEST-DEVICES.md](docs/VENDOR-GAPS-AND-TEST-DEVICES.md) | per-vendor gaps, required real devices, HW-1..HW-8 |
| [docs/NOTIFICATION-ACTION.md](docs/NOTIFICATION-ACTION.md) | separate action design, tag contract, safety, HW-N1..N6 |
| [docs/HANDOFF-TO-CODEX.md](docs/HANDOFF-TO-CODEX.md), [docs/HANDOFF-V0.2.1.md](docs/HANDOFF-V0.2.1.md) | what to run next, blockers |
| [docs/SYNTHETIC-NOTIFICATION-TEST.md](docs/SYNTHETIC-NOTIFICATION-TEST.md) | LAB synthetic delivery test plan: per-recipient message counts, preflight, id ledger, before/after manifest, ID-scoped cleanup (NOT executed; needs explicit operator authorization) |
| [docs/LAB-DISCOVERY-2026-10-09.md](docs/LAB-DISCOVERY-2026-10-09.md) | Codex's discovery report (unchanged) |
| [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md) | mandatory four-vendor acceptance gates (unchanged) |

## Not done, deliberately
Building tagged hardware triggers (needs a real device to prove what each item returns); populating the LAB inventory; enabling the action; anything in Production; changes to Interface Alerting v1.0.2.

### Synthetic-test support (read-only against Zabbix)
```bash
python3 hardware_audit.py --env lab synthetic preflight|snapshot|cleanup-plan|verify   # reads only; refuses on any pre-existing synthetic object
python3 hardware_audit.py --env lab synthetic diff --before B.json --after A.json
python3 hardware_audit.py --env lab synthetic ledger-record|ledger-mark ...            # local ledger file only
```

# NETOPS Hardware Health (independent project)

**Status: v0.2 LAB tooling. Audit corrected and offline-tested (125 tests, v0.2.1). Hardware coverage is NOT accepted anywhere and hardware notifications are NOT operational.**

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

## Rules the tool enforces

* **Read-only audit.** Allowed API methods: `apiinfo.version`, `host.get`, `item.get`, `trigger.get`, `usermacro.get`, `action.get`, `usergroup.get`, `mediatype.get`. Only `action apply|rollback` opens a write client, limited to `action.create|update|delete`.
* **Server-side identity.** The Zabbix being queried must report `{$NETOPS.ENVIRONMENT}` equal to `--env`; a mismatch or a missing macro stops the run before any host is read. LAB and Production use different URLs, tokens and policy files; Production requires `zabbix.url_regex`.
* **No keyword coverage.** A sensor is covered only if the approved policy declares its exact item key and live Zabbix shows a concrete (non-raw-walk), enabled, supported, fresh item whose value is interpretable through a **verified** vendor mapping, with an enabled trigger bound to that item carrying `netops_hardware=1` and the matching `hardware_component`.
* **No invented vendor data.** `config/status-semantics.yaml` ships empty. A mapping needs `verified: true`, an evidence reference and the same vendor; it is never reused across vendors.
* **HA is not hardware redundancy.** Separate categories, separate sensors, separate triggers (Fortinet and Palo Alto HA vs fan/PSU redundancy).
* **Missing data is not a fault.** An unreachable device makes its sensors BLOCKED; nothing is inferred about fans or PSUs from an SNMP timeout.
* **Empty approved inventories.** `config/hardware.lab.yaml` and `config/hardware.production.yaml` are `hosts: {}` until a real model's sensors are verified.

## Documents

| | |
|---|---|
| [docs/AUDIT-CORRECTIONS.md](docs/AUDIT-CORRECTIONS.md) | defect -> fix -> regression test |
| [docs/COVERAGE-MATRIX.md](docs/COVERAGE-MATRIX.md) | four-vendor matrix from the 2026-10-09 discovery |
| [docs/VENDOR-GAPS-AND-TEST-DEVICES.md](docs/VENDOR-GAPS-AND-TEST-DEVICES.md) | per-vendor gaps, required real devices, HW-1..HW-8 |
| [docs/NOTIFICATION-ACTION.md](docs/NOTIFICATION-ACTION.md) | separate action design, tag contract, safety, HW-N1..N6 |
| [docs/HANDOFF-TO-CODEX.md](docs/HANDOFF-TO-CODEX.md), [docs/HANDOFF-V0.2.1.md](docs/HANDOFF-V0.2.1.md) | what to run next, blockers |
| [docs/SYNTHETIC-NOTIFICATION-TEST.md](docs/SYNTHETIC-NOTIFICATION-TEST.md) | reversible LAB synthetic delivery test (needs explicit approval; not executed) |
| [docs/LAB-DISCOVERY-2026-10-09.md](docs/LAB-DISCOVERY-2026-10-09.md) | Codex's discovery report (unchanged) |
| [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md) | mandatory four-vendor acceptance gates (unchanged) |

## Not done, deliberately
Building tagged hardware triggers (needs a real device to prove what each item returns); populating the LAB inventory; enabling the action; anything in Production; changes to Interface Alerting v1.0.2.

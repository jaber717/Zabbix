# NETOPS Hardware Health — Mandatory four-vendor acceptance

Hardware Health is independent of Interface Alerting v1.0.2.
The four mandatory vendor families are **Cisco, Palo Alto Networks, Fortinet and Huawei**.
Do not call the project complete if any family has not been investigated.

## Vendor and platform validation

| Vendor | Target family | Required device-specific investigation |
| --- | --- | --- |
| Cisco | ASR 8500 / IOS-XR, Nexus / NX-OS, IOS/IOS-XE | Fan trays, power supplies, temperature, redundancy, ENTITY/vendor-specific MIBs |
| Palo Alto Networks | PA-Series / PAN-OS | Physical environmental status via supported vendor SNMP/API, HA/member specificity |
| Fortinet | FortiGate, FortiProxy if installed | Device-model-specific sensor/PSU/Fan telemetry via supported MIB/API, HA/cluster handling |
| Huawei | S-series switches, AR8140 / VRP routers | Huawei-specific environmental sensors, fans, PSU and thermal alarms |

F5 is deferred from the current mandatory scope, unless separately requested.
For models or vendors absent from LAB, mark acceptance **BLOCKED / NOT TESTABLE**, never PASS.
Do not assume all vendors expose the same OIDs or operational-status mappings.

## Required alarm families

| Category | Problem criteria | Recovery criteria |
| --- | --- | --- |
| Fan | Fan or fan tray failed, degraded, absent unexpectedly | Normal operation restored |
| Power | PSU failed, input lost, power module not present unexpectedly | Verified normal power |
| Temperature | Manufacturer-specific warning/critical or meaningful high reading | Below configured recovery threshold |
| Redundancy | N+1 fan or PSU redundancy degraded where supported | Redundancy restored |
| Monitoring quality | Sensor unsupported/stale; host SNMP unavailable | Fresh supported data returns |

Do not conflate a missing SNMP response with a PSU/Fan failure.
Mark a model without a component or supported sensor as **N/A with evidence** (not implicitly green).

## Per-model coverage report required from Codex

For EACH actual device, record site, vendor, exact model, OS version, Zabbix template, SNMPv3/API method (not secrets), sample timestamps, monitored component/slot, sensor status semantics, actual item keys/OIDs or API fields, supported/fresh status, hardware trigger and severity, event tags, and problem/recovery proof. Deliver separate Cisco, Palo Alto, Fortinet and Huawei coverage matrices. Make missing capabilities explicit.

## Architecture

- Preserve all existing Zabbix stock and vendor monitoring wherever reliable.
- Create only genuinely missing vetted vendor-specific items/triggers; do not duplicate hardware alerts.
- Use a dedicated `NETOPS Hardware Health` Action with verified strict event tags and user group/media.
- Never route `netops_alert` events to Hardware Health or hardware events to NETOPS Interface Alerting.
- Alert payload includes vendor/model, site, host, physical slot, component, severity, timestamp, event ID and recovery state.
- Support email in Production, Telegram in LAB where permitted.
- YAML-first device policy; separate LAB and Production inventories, credentials and environment identity.
- No writes to Production; no changes to the frozen Interface Alerting v1.0.2.
- No auto-enable of unverified vendor templates, SNMP discovery or router configuration.

## Gates

1. **Discovery:** real read-only Zabbix 7.0.30 item/trigger/tag inspection for all four vendors, supported data and freshness checked.
2. **Build:** Claude reviews vendor findings; adds only missing telemetry/notification policy; automated tests and safe dry-run, backup, idempotency and rollback.
3. **Live LAB acceptance:** independent Codex verification of Fan, PSU, Temperature, redundancy and monitoring-loss semantics per vendor; appropriate PASS/GAP/N/A/BLOCKED per model.
4. **Notifications:** prove real or safely simulated Problem and Recovery without modifying hardware; demonstrate no cross-notification with Interface Alerting. Do not claim a real hardware failure test unless it actually happened safely.
5. **Release:** no production promotion unless all required gates pass or limitations receive explicit approval; no secrets in code, logs or Git.

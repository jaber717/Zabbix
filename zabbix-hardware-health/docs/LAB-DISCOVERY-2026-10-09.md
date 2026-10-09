# NETOPS Hardware Health — read-only LAB discovery

Source branch: `feature/netops-hardware-health` at `d6c2ed0241b9a214d6f3340f6941ec57e7abf147`.
Environment: Zabbix API 7.0.30, `{$NETOPS.ENVIRONMENT}=lab`.
Scope: Zabbix API reads and offline tests only; no Zabbix, SNMP device, Interface Alerting, or Production write.

## Result

**Hardware coverage is not accepted.** The LAB has no verified fresh physical fan, PSU, temperature, or hardware redundancy sensor values. The approved LAB inventory remains `hosts: {}` for that reason. The empty-inventory audit returned exit 3, `No approved hosts in inventory. Audit not run.` This is the intended fail-closed result, not a monitoring PASS.

The audit was also exercised read-only using a temporary, explicitly *unapproved* probe inventory for `PNET-SITE-A`, `DR-LEAF01`, and `DR-FW01`. It returned exit 2 with 0 covered and 3 review-required hosts. That temporary probe inventory was removed and was never proposed as a deployable policy.

## Implementation checks

- `hardware_audit.py` compiled on the LAB RHEL 9 Python 3.9.21 runtime with PyYAML available.
- All 9 project unit tests passed.
- The API method allowlist contains only `apiinfo.version`, `host.get`, `item.get`, and `trigger.get`.
- Read-only live queries used an existing authorized LAB token; a dedicated Hardware Health token was not configured. No credential is in this repository or evidence.
- The script correctly reported 0 covered hosts in the temporary probe run. It did **not** create or change any Zabbix object.
- Audit defect: the Cisco IOSv `sensor.fans.walk`, `sensor.psu.walk`, and `sensor.temp.walk` raw discovery inputs were counted as one sensor item each. Their `lastclock` is zero, no concrete sensor was discovered, and no host hardware trigger exists. The result `NO_ENABLED_TRIGGERS` understates the actual absence of a sensor. Exclude raw walk/discovery items from concrete sensor counts and test this case.
- Audit limitation: `item.get` does not request `lastvalue`, units, value type, preprocessing, or the actual sensor OID, so the audit cannot prove a supported sensor's operational value or map an alarm state to vendor semantics. Host inventory model/version is likewise not read. These fields are required for the per-model acceptance matrix.
- Audit limitation: `classify()` does not recognize FortiGate `ha.*` as redundancy. The mock FortiGate has seven static HA-related items, but all are undated and there is no enabled HA trigger; this must still remain uncovered.
- Isolation gap to close before any write-capable tooling: `hardware_audit.py` selects a URL from the environment and an inventory `environment` field, but does not read and compare the server-side `{$NETOPS.ENVIRONMENT}` macro. A mispointed URL would not be detected by the audit itself. The live LAB identity was separately confirmed during discovery; future deployment must fail closed on a server-side identity mismatch.

## Real LAB host and sensor inventory

| Device group | Count | Zabbix template | Fan | PSU | Temperature | Redundancy | Live conclusion |
|---|---:|---|---|---|---|---|---|
| PNET WAN routers (`INT-CORE`, `MOBILY`, `SAIX-A/B`, `SITE-A/B`, `STC`) | 7 | Cisco IOS by SNMP + NETOPS Interface Alerting | 0 discovered items | 0 discovered items | 0 discovered items | 0 | IOSv virtual routers. Template has three raw environmental walks and seven relevant trigger prototypes, but each raw walk has `lastclock=0`; no physical sensor is demonstrated. |
| `DR-LEAF01/02` | 2 | Cisco Nexus 9000 Series by SNMP | 0 | 0 | 0 | 0 | Intentional mock hosts; template definitions exist, but no real device data. |
| `DR-FW01` | 1 | FortiGate by SNMP | 0 | 0 | 0 | Seven HA-related static items, none fresh; 0 enabled HA triggers | Intentional mock host; no physical or HA state is proven. |
| `DR-LB01` | 1 | F5 Big-IP by SNMP | 0 | 0 | 0 | Sync status exists but is stale | Intentional mock, and F5 is outside the mandatory four-vendor gate. |

All 11 network hosts' SNMP interfaces reported unavailable. The Cisco IOSv raw fan/PSU/temperature walks across seven routers total 21 items, and **0/21** had ever recorded a sample. Relevant model/sysDescr/sysObjectID items also had no value. A previously sampled general WAN item was last updated on 2026-10-08 around 08:49 Asia/Riyadh, whereas the discovery audit ran on 2026-10-09 around 03:58. No hardware sensor value could be verified as fresh or supported.

## Four-vendor coverage matrix

| Vendor and target family | Current LAB evidence | Fan | PSU | Temperature | Redundancy | Acceptance |
|---|---|---|---|---|---|---|
| Cisco IOS/IOS-XE | Seven PNET IOSv hosts use Cisco IOS template. Template has fan/PSU/temperature discovery and seven hardware trigger prototypes tagged only `scope=availability` and/or `scope=performance`. | No discovered values | No discovered values | No discovered values | No evidence | GAP / physical component applicability unverified |
| Cisco Nexus/NX-OS | Two DR mock hosts use Nexus 9000 template. It defines fan/PSU/temperature discovery and 11 related trigger prototypes, but the mock hosts have no discovered sensors. | No live values | No live values | No live values | No evidence | NOT TESTABLE on mock hosts |
| Cisco ASR 8500/IOS-XR | No monitored ASR host or matching verified model was found. | — | — | — | — | BLOCKED / NOT TESTABLE |
| Palo Alto PA-Series/PAN-OS | No Palo Alto Zabbix host. The available PA-440 HTTP template has HA state/link/sync checks and a CPU-temperature item, but no live validation; no fan/PSU coverage was found in inspected template definitions. | No host | No host | Template item only | Template HA checks only | BLOCKED / NOT TESTABLE |
| Fortinet FortiGate | `DR-FW01` is an intentional mock with the FortiGate SNMP template. It defines generic hardware-sensor and HA-member discovery, but no hardware or HA trigger prototype appeared in the inspected template, and no sensor was discovered. | No live values | No live values | No live values | Undated HA items only | NOT TESTABLE; trigger gap in inspected template |
| Fortinet FortiProxy | No host/template confirmed. | — | — | — | — | BLOCKED / NOT TESTABLE |
| Huawei VRP S-series / AR8140 | No Huawei Zabbix host. The installed Huawei VRP template defines fan and temperature prototypes and related triggers tagged `scope`; no PSU or redundancy monitoring was found in inspected definitions. AR8140 mapping was not validated. | Template only | No inspected definition | Template only | No inspected definition | BLOCKED / NOT TESTABLE |

These are Zabbix template and host observations. They are not a claim about what any absent physical model can or cannot expose. Do not mark an unobserved component N/A; N/A requires model-specific proof.

## Event tags and notification action

- Current Cisco IOS, Nexus, Huawei, PA-440, and F5 hardware trigger prototypes use broad `scope` values such as `availability`, `performance`, or `notice`. Those values are shared with non-hardware triggers and are unsafe as the sole action filter.
- The active `NETOPS-IaC Interface Alerts` action filters on event tag name `netops_alert`; no separate NETOPS Hardware Health action exists. The previous 30-day event query found no real fan/PSU/temperature/redundancy hardware event. Two hardware-sounding events were unrelated Linux `component=system` notices.
- Recommended policy for Claude after trigger-by-trigger validation: add `netops_hardware=1` only to vetted hardware triggers; add `hardware_component=fan|power|temperature|redundancy|sensor_stale` and optional vendor/model/slot tags for routing and payloads. Do not place `netops_alert` on them.
- Recommended **trigger action** filter: `evaltype=1` (AND); condition A: `conditiontype=26` (event tag value), `operator=0`, `value=netops_hardware`, `value2=1`; condition B: `conditiontype=25` (event tag), `operator=1` (does not equal), `value=netops_alert`. The dedicated tag is the positive allowlist; B guards against accidental cross-tagging. Keep the action disabled until actual Problem and Recovery delivery and exclusion tests pass.
- Do not route on host group alone, trigger name text, or broad `scope` tags. Keep media, recipient group, and Problem/Recovery operations independent of the Interface Alerting action.
- Zabbix 7.0 API condition types and operators: [official Action object reference](https://www.zabbix.com/documentation/7.0/en/manual/api/reference/action/object). Action condition combination: [official notification conditions](https://www.zabbix.com/documentation/7.0/en/manual/config/notifications/action/conditions).

## Claude implementation handoff

1. Correct the audit's concrete-sensor classification; include actual values, timestamps, OIDs, units, and model identity in a redacted per-device report. Preserve its read-only API allowlist.
2. Obtain a LAB host for each required physical platform family, or record each absent family as NOT TESTABLE. Confirm model, OS, component slots, SNMPv3/API semantics, and whether each component is physically present before populating `config/hardware.lab.yaml`.
3. Reuse verified stock/vendor items and triggers. Add only missing model-specific checks; prove status and recovery mappings with safe evidence. Do not infer a PSU failure from SNMP timeout.
4. Add a dedicated, disabled-by-default Hardware Health action and strict tags as above. Validate actual Fan/PSU/temperature/HA Problem and Recovery delivery and prove no interface or unrelated notification crossover.
5. Add safe dry-run, ownership checks, idempotence, backup, and rollback before any deployment. Run independent live LAB acceptance afterward. Hardware notification delivery is **NOT TESTED** at this stage.

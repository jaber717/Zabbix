# NETOPS Hardware Health - coverage matrix

PASS = real, fresh, supported sensor with a verified status meaning and a dedicated-tag trigger bound to it. GAP = monitoring missing or unusable. BLOCKED = cannot be judged (no device, unreachable, mock host). N/A = only with model-specific evidence. Nothing here is a claim about what an absent physical model can or cannot expose.

Totals over all vendor x category cells: PASS 0, GAP 5, BLOCKED 33, N/A 0.

## Cisco

### Cisco IOS / IOS-XE (`cisco-iosxe`)

Devices: INT-CORE, MOBILY, SAIX-A, SAIX-B, SITE-A, SITE-B, STC (Cisco IOSv virtual router (model/sysDescr/sysObjectID items had no value))

| Category | Verdict | Evidence |
|---|---|---|
| fan | **GAP** | INT-CORE, MOBILY, SAIX-A, SAIX-B, SITE-A, SITE-B, STC [GAP]: raw sensor.fans.walk input never sampled (0 of 7 hosts); no concrete fan sensor discovered; template trigger prototypes exist but no host trigger - Codex LAB discovery 2026-10-09 @281361c |
| power | **GAP** | INT-CORE, MOBILY, SAIX-A, SAIX-B, SITE-A, SITE-B, STC [GAP]: raw sensor.psu.walk input never sampled (0 of 7 hosts); no concrete PSU sensor discovered - Codex LAB discovery 2026-10-09 @281361c |
| temperature | **GAP** | INT-CORE, MOBILY, SAIX-A, SAIX-B, SITE-A, SITE-B, STC [GAP]: raw sensor.temp.walk input never sampled (0 of 7 hosts); no concrete temperature sensor discovered - Codex LAB discovery 2026-10-09 @281361c |
| hw_redundancy | **GAP** | INT-CORE, MOBILY, SAIX-A, SAIX-B, SITE-A, SITE-B, STC [GAP]: no redundancy evidence of any kind; all SNMP interfaces were unavailable at discovery - Codex LAB discovery 2026-10-09 @281361c |

### Cisco Nexus / NX-OS (`cisco-nxos`)

Devices: DR-LEAF01, DR-LEAF02 (Cisco Nexus 9000 Series by SNMP template on an intentional MOCK host (non-routable address))

| Category | Verdict | Evidence |
|---|---|---|
| fan | **BLOCKED** | DR-LEAF01, DR-LEAF02 [BLOCKED]: mock host: template defines discovery and triggers but no real device data; NOT TESTABLE - Codex LAB discovery 2026-10-09 @281361c |
| power | **BLOCKED** | DR-LEAF01, DR-LEAF02 [BLOCKED]: mock host: no discovered sensors; NOT TESTABLE - Codex LAB discovery 2026-10-09 @281361c |
| temperature | **BLOCKED** | DR-LEAF01, DR-LEAF02 [BLOCKED]: mock host: no discovered sensors; NOT TESTABLE - Codex LAB discovery 2026-10-09 @281361c |
| hw_redundancy | **BLOCKED** | DR-LEAF01, DR-LEAF02 [BLOCKED]: mock host: no evidence; NOT TESTABLE - Codex LAB discovery 2026-10-09 @281361c |

### Cisco ASR 8500 / IOS-XR (`cisco-asr8500`)

Devices: none

| Category | Verdict | Evidence |
|---|---|---|
| fan | **BLOCKED** | no device of this family is monitored in this environment (NOT TESTABLE) |
| power | **BLOCKED** | no device of this family is monitored in this environment (NOT TESTABLE) |
| temperature | **BLOCKED** | no device of this family is monitored in this environment (NOT TESTABLE) |
| hw_redundancy | **BLOCKED** | no device of this family is monitored in this environment (NOT TESTABLE) |

## Palo Alto Networks

### Palo Alto PA-Series / PAN-OS (`paloalto-panos`)

Devices: none

| Category | Verdict | Evidence |
|---|---|---|
| fan | **BLOCKED** | no device of this family is monitored in this environment (NOT TESTABLE) |
| power | **BLOCKED** | no device of this family is monitored in this environment (NOT TESTABLE) |
| temperature | **BLOCKED** | no device of this family is monitored in this environment (NOT TESTABLE) |
| hw_redundancy | **BLOCKED** | no device of this family is monitored in this environment (NOT TESTABLE) |
| ha | **BLOCKED** | no device of this family is monitored in this environment (NOT TESTABLE) |
| sensor | **BLOCKED** | no device of this family is monitored in this environment (NOT TESTABLE) |

## Fortinet

### Fortinet FortiGate (`fortinet-fortigate`)

Devices: DR-FW01 (FortiGate by SNMP template on an intentional MOCK host)

| Category | Verdict | Evidence |
|---|---|---|
| fan | **BLOCKED** | DR-FW01 [BLOCKED]: mock host: generic hardware-sensor discovery defined, no sensor discovered; NOT TESTABLE - Codex LAB discovery 2026-10-09 @281361c |
| power | **BLOCKED** | DR-FW01 [BLOCKED]: mock host: no sensor discovered; NOT TESTABLE - Codex LAB discovery 2026-10-09 @281361c |
| temperature | **BLOCKED** | DR-FW01 [BLOCKED]: mock host: no sensor discovered; NOT TESTABLE - Codex LAB discovery 2026-10-09 @281361c |
| hw_redundancy | **BLOCKED** | DR-FW01 [BLOCKED]: mock host: no hardware-redundancy evidence; NOT TESTABLE - Codex LAB discovery 2026-10-09 @281361c |
| ha | **BLOCKED** | DR-FW01 [BLOCKED]: seven static HA-related items, all undated, and 0 enabled HA triggers; mock host so HA state is not proven. HA is a separate category from hw_redundancy - Codex LAB discovery 2026-10-09 @281361c |
| sensor | **GAP** | devices exist but nothing was recorded for this category |

### Fortinet FortiProxy (`fortinet-fortiproxy`)

Devices: none

| Category | Verdict | Evidence |
|---|---|---|
| fan | **BLOCKED** | no device of this family is monitored in this environment (NOT TESTABLE) |
| power | **BLOCKED** | no device of this family is monitored in this environment (NOT TESTABLE) |
| temperature | **BLOCKED** | no device of this family is monitored in this environment (NOT TESTABLE) |
| hw_redundancy | **BLOCKED** | no device of this family is monitored in this environment (NOT TESTABLE) |
| ha | **BLOCKED** | no device of this family is monitored in this environment (NOT TESTABLE) |
| sensor | **BLOCKED** | no device of this family is monitored in this environment (NOT TESTABLE) |

## Huawei

### Huawei S-series / VRP switch (`huawei-vrp-switch`)

Devices: none

| Category | Verdict | Evidence |
|---|---|---|
| fan | **BLOCKED** | no device of this family is monitored in this environment (NOT TESTABLE) |
| power | **BLOCKED** | no device of this family is monitored in this environment (NOT TESTABLE) |
| temperature | **BLOCKED** | no device of this family is monitored in this environment (NOT TESTABLE) |
| hw_redundancy | **BLOCKED** | no device of this family is monitored in this environment (NOT TESTABLE) |

### Huawei AR8140 / VRP router (`huawei-ar8140`)

Devices: none

| Category | Verdict | Evidence |
|---|---|---|
| fan | **BLOCKED** | no device of this family is monitored in this environment (NOT TESTABLE) |
| power | **BLOCKED** | no device of this family is monitored in this environment (NOT TESTABLE) |
| temperature | **BLOCKED** | no device of this family is monitored in this environment (NOT TESTABLE) |
| hw_redundancy | **BLOCKED** | no device of this family is monitored in this environment (NOT TESTABLE) |


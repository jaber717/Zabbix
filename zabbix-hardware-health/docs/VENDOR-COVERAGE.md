# NETOPS Hardware Health - vendor coverage matrix

Generated from `vendors/*.yaml`. Every OID / API path / enumeration comes from a cited vendor MIB or official Zabbix 7.0 template (see the definition's `sources`). **DOCUMENTATION-DERIVED, NOT DEVICE-VERIFIED:** nothing here has been observed on real equipment, and the SNMP Simulator verifies the pipeline, not any vendor's behaviour. Levels are kept apart: IMPLEMENTED < SIMULATED TESTED < REAL DEVICE VERIFIED; UNVERIFIED / BLOCKED means nothing is claimed.

Cells: SIMULATED TESTED 11, UNVERIFIED / BLOCKED 27.

| Family | Category | Level | Implemented as | Readings only (no alert) | Not available / reason |
|---|---|---|---|---|---|
| Cisco ASR 8500 / IOS-XR | fan | UNVERIFIED / BLOCKED | - | - | No definition: the target model is unconfirmed. If it is an ASR 9000 (IOS XR), cefcFanTrayOperStatus is MIB-verified but the rows returned by the chassis are not documented; a device walk is required. |
| Cisco ASR 8500 / IOS-XR | power | UNVERIFIED / BLOCKED | - | - | No definition: the target model is unconfirmed. On IOS XR, power data is reported as admin-restricted (SystemOwner). |
| Cisco ASR 8500 / IOS-XR | temperature | UNVERIFIED / BLOCKED | - | - | No definition: the target model is unconfirmed. |
| Cisco ASR 8500 / IOS-XR | hw_redundancy | UNVERIFIED / BLOCKED | - | - | No definition. |
| Cisco IOS / IOS-XE | fan | SIMULATED TESTED | Fan state [status] | - | - |
| Cisco IOS / IOS-XE | power | SIMULATED TESTED | Power supply state [status] | - | - |
| Cisco IOS / IOS-XE | temperature | SIMULATED TESTED | Temperature test point state (device-reported) [status] | Temperature reading (informational) | - |
| Cisco IOS / IOS-XE | hw_redundancy | UNVERIFIED / BLOCKED | - | - | No redundancy object is defined by the reference template; none is defined here. Not verified. |
| Cisco Nexus / NX-OS | fan | SIMULATED TESTED | Fan / fan tray operational state [status] | - | - |
| Cisco Nexus / NX-OS | power | SIMULATED TESTED | Power supply (FRU) operational state [status] | - | - |
| Cisco Nexus / NX-OS | temperature | SIMULATED TESTED | Temperature sensor health (NOT an over-temperature alarm) [sensor-health] | - | Over-temperature alarm (entSensorValue with scale/precision and thresholds) is not implemented; only sensor health is. |
| Cisco Nexus / NX-OS | hw_redundancy | UNVERIFIED / BLOCKED | - | - | No redundancy object is defined by the reference template; none is defined here. |
| Fortinet FortiGate | fan | UNVERIFIED / BLOCKED | - | - | FortiGate exposes fans only as generically named rows of fgHwSensorEntTable; which rows are fans is model dependent. Not classified. |
| Fortinet FortiGate | power | UNVERIFIED / BLOCKED | - | - | No dedicated PSU object in the reference template. Not defined. |
| Fortinet FortiGate | temperature | UNVERIFIED / BLOCKED | - | - | Temperature rows of fgHwSensorEntTable are generic and unit-less strings (fgHwSensorEntValue). Not defined. |
| Fortinet FortiGate | hw_redundancy | UNVERIFIED / BLOCKED | - | - | Not defined by the reference template. HA is a separate category. |
| Fortinet FortiGate | ha | SIMULATED TESTED | HA member synchronisation [status] | - | - |
| Fortinet FortiGate | sensor | SIMULATED TESTED | Hardware sensor alarm (generic - the sensor name decides whether it is a fan, PSU or temperature sensor) [status] | - | - |
| Fortinet FortiProxy | fan | UNVERIFIED / BLOCKED | - | - | No documented FortiProxy fan object found; MIB not publicly available. Obtain FORTINET-FORTIPROXY-MIB from Fortinet support. |
| Fortinet FortiProxy | power | UNVERIFIED / BLOCKED | - | - | No documented FortiProxy power-supply object found. |
| Fortinet FortiProxy | temperature | UNVERIFIED / BLOCKED | - | - | No documented FortiProxy temperature object found. |
| Fortinet FortiProxy | hw_redundancy | UNVERIFIED / BLOCKED | - | - | No definition. |
| Fortinet FortiProxy | ha | UNVERIFIED / BLOCKED | - | - | No documented FortiProxy HA object found; FortiGate's fgHaStatsSyncStatus (12356.101.13) is not assumed. |
| Fortinet FortiProxy | sensor | UNVERIFIED / BLOCKED | - | - | No definition. |
| Huawei AR8140 / VRP router | fan | SIMULATED TESTED | Fan state [status] | - | - |
| Huawei AR8140 / VRP router | power | UNVERIFIED / BLOCKED | - | - | The reference template defines no power-supply object. Not defined. |
| Huawei AR8140 / VRP router | temperature | UNVERIFIED / BLOCKED | - | Entity temperature reading (informational) | No alarm: requires operator-approved thresholds per model. |
| Huawei AR8140 / VRP router | hw_redundancy | UNVERIFIED / BLOCKED | - | - | Not defined by the reference template. |
| Huawei S-series / VRP switch | fan | SIMULATED TESTED | Fan state [status] | - | - |
| Huawei S-series / VRP switch | power | UNVERIFIED / BLOCKED | - | - | The reference template defines no power-supply object. Not defined. |
| Huawei S-series / VRP switch | temperature | UNVERIFIED / BLOCKED | - | Entity temperature reading (informational) | No alarm: requires operator-approved thresholds per model. |
| Huawei S-series / VRP switch | hw_redundancy | UNVERIFIED / BLOCKED | - | - | Not defined by the reference template. |
| Palo Alto PA-Series / PAN-OS | fan | UNVERIFIED / BLOCKED | - | - | Fan state is not in the reference template; the response layout of the environmentals command for fans is not documented here. UNVERIFIED. |
| Palo Alto PA-Series / PAN-OS | power | UNVERIFIED / BLOCKED | - | - | Power-supply state is not in the reference template; the response layout is not documented here. UNVERIFIED. |
| Palo Alto PA-Series / PAN-OS | temperature | UNVERIFIED / BLOCKED | - | System temperature reading (informational, PA-440 layout) | No alarm: no documented threshold. Reading only. |
| Palo Alto PA-Series / PAN-OS | hw_redundancy | UNVERIFIED / BLOCKED | - | - | Not defined. HA is a separate category. |
| Palo Alto PA-Series / PAN-OS | ha | SIMULATED TESTED | HA state of the local firewall [status] | - | - |
| Palo Alto PA-Series / PAN-OS | sensor | UNVERIFIED / BLOCKED | - | - | Generic hardware-sensor alarm is not defined for PAN-OS; fan/power/temperature are covered by their own categories above. |

## Simulation results

- `cisco-asr8500`: 0 scenario checks, 0 failed
- `cisco-iosxe`: 38 scenario checks, 0 failed
- `cisco-nxos`: 38 scenario checks, 0 failed
- `fortinet-fortigate`: 12 scenario checks, 0 failed
- `fortinet-fortiproxy`: 0 scenario checks, 0 failed
- `huawei-vrp`: 7 scenario checks, 0 failed
- `paloalto-panos`: 14 scenario checks, 0 failed

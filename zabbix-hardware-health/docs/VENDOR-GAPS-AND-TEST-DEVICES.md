# Vendor-specific gaps and the real devices required

Source of facts: Codex's read-only LAB discovery (`LAB-DISCOVERY-2026-10-09.md`, branch `codex/hardware-health-lab-discovery` @ 281361c). The generated matrix is [COVERAGE-MATRIX.md](COVERAGE-MATRIX.md): **0 PASS, 4 GAP, 31 BLOCKED, 0 N/A** over the 35 vendor x category cells. Nothing is accepted.

## Gaps common to all four vendors

1. No LAB host has a verified, fresh, physical fan / PSU / temperature / redundancy sensor. IOSv routers are virtual; DR network hosts are mocks with non-routable addresses; all 11 network hosts' SNMP interfaces were unavailable.
2. No vendor status mapping is verified. `config/status-semantics.yaml` is empty on purpose; until a mapping is confirmed from the vendor MIB/API (or a device capture), a status sensor can only be `SEMANTICS_UNVERIFIED`.
3. No hardware trigger carries the dedicated tags (`netops_hardware`, `hardware_component`); stock triggers use shared `scope`/`component` tags. Mechanism for tagging is an open decision (NOTIFICATION-ACTION.md).
4. Delivery of hardware Problem/Recovery notifications has never been tested.

## Per vendor

| Vendor / family | Observed in LAB | Gap | Needs |
|---|---|---|---|
| **Cisco IOS / IOS-XE** | 7 IOSv routers on `Cisco IOS by SNMP`; template has 3 raw environmental walks + 7 hardware trigger prototypes (tags `scope` only). 0/21 raw walks ever sampled; no concrete sensor discovered; model items empty. | GAP in all four categories. A virtual platform may legitimately have no fans/PSUs, but that is **not** N/A without model-specific proof. | A real IOS-XE device (see below) and, for the IOSv, either proof of its component set or an explicit N/A with evidence. |
| **Cisco Nexus / NX-OS** | `DR-LEAF01/02` mock hosts, `Cisco Nexus 9000 Series by SNMP`; template defines fan/PSU/temperature discovery and 11 related trigger prototypes. | BLOCKED: no real data. | A real Nexus switch. |
| **Cisco ASR 8500 / IOS-XR** | No host, no matching verified model. | BLOCKED. | A real ASR 8500 (or a written decision that the family is out of scope). |
| **Palo Alto PA-Series / PAN-OS** | No host. A PA-440 HTTP template exists with HA state/link/sync checks and one CPU-temperature item; no fan/PSU coverage in the inspected definitions. | BLOCKED. Likely fan/PSU gap even with the template. HA must be tracked as `ha`. | A real PA firewall; if HA is in use, a pair. |
| **Fortinet FortiGate** | `DR-FW01` mock, `FortiGate by SNMP`; generic hardware-sensor and HA-member discovery defined; no hardware/HA trigger prototype in the inspected template; 7 undated static HA items. | BLOCKED. Trigger gap for both hardware sensors and HA in the inspected template. HA and hardware redundancy are separate categories and are audited separately. | A real FortiGate; an HA pair for HA/member testing. |
| **Fortinet FortiProxy** | None. | BLOCKED. | A real FortiProxy, or a written decision that none is deployed. |
| **Huawei VRP S-series** | No host. Installed Huawei VRP template defines fan and temperature prototypes + triggers (tag `scope`); no PSU or redundancy found in inspected definitions. | BLOCKED. Probable PSU and redundancy gap. | A real S-series switch (and a stack if used). |
| **Huawei AR8140** | Mapping not validated; no host. | BLOCKED. | A real AR8140. |

F5 BIG-IP (mock `DR-LB01`) is deferred and outside the four-vendor gate.

## Real test devices required (minimum)

One real, SNMP-reachable unit per family above that is actually deployed (or a written scope decision per family). For each unit, before it enters `config/hardware.lab.yaml`:

* exact model, OS/software version, chassis components and slot map (which fans/PSUs/sensors physically exist -> this is also the only basis for any N/A);
* an SNMPv3 (or API) read-only account usable from the Zabbix server, and Zabbix reaching it (this was the LAB's blocker: management addresses unreachable);
* a **sysDescr / sysObjectID capture** and a **read-only walk of the vendor's environmental and entity/HA data**, to establish the real item keys/OIDs and the real status codes. The MIB names to consult are candidate sources only, to be confirmed by that capture, not a mapping: CISCO-ENVMON-MIB and ENTITY-SENSOR-MIB (Cisco), PAN-COMMON-MIB and the PAN-OS API/CLI environmental output (Palo Alto), FORTINET-FORTIGATE-MIB (Fortinet), HUAWEI-ENTITY-EXTENT-MIB / ENTITY-MIB (Huawei);
* the vendor's documentation (or capture) that defines each status value -> only then an entry in `config/status-semantics.yaml` with its evidence;
* for redundancy: a chassis/configuration that actually has N+1 fans or PSUs; for HA: a real pair.

Safe event generation (no unsafe damage): prefer Zabbix-side simulation (lowering a temperature threshold macro on the LAB trigger, or a maintenance-window removal/replacement of a redundant PSU or fan tray only by the device owner). Never claim a real failure test unless it actually and safely happened.

## Acceptance tests per device (HW-1 .. HW-8)

| ID | Test |
|---|---|
| HW-1 | `discover --host`: raw inputs vs concrete sensors; values, timestamps, units, OIDs, preprocessing, value maps, model identity recorded |
| HW-2 | model and component inventory recorded; sensors declared in the policy with verified semantics |
| HW-3 | `audit`: every declared sensor PASS (collected, supported, fresh, mapped) |
| HW-4 | trigger per sensor bound to the item, carrying the dedicated tags |
| HW-5 | Problem and Recovery state change for fan, PSU, temperature (real or safely simulated) |
| HW-6 | redundancy and (Fortinet/Palo Alto) HA tested separately |
| HW-7 | monitoring loss (SNMP unreachable / stale) reported as `sensor_stale` / BLOCKED, never as a hardware failure |
| HW-8 | notification delivery through the separate action (HW-N1..N6) |

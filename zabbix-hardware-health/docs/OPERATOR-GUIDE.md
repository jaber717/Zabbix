# Operator guide

## What the engine does
Per vendor definition (`vendors/*.yaml`) the tool generates a Zabbix 7.0 template `NETOPS-HW <definition>`:

1. a **walk master item** (or HTTP-agent item for PAN-OS) that reads the vendor table in one request;
2. a **dependent discovery rule** that finds each fan / PSU / temperature sensor by the *presence of its value column* (not by name matching);
3. **dependent item prototypes** with a value map showing the vendor's own wording;
4. **trigger prototypes** per non-normal class (e.g. `degraded` = Warning, `failed` = High), each with:
   * **confirm samples** (2 for `failed`, 3 for `degraded`) - a single odd sample never raises a problem;
   * a **recovery expression** needing consecutive normal samples - a flapping sensor does not clear/re-raise;
   * routing tags `netops_hardware=1`, `hardware_component`, `hardware_vendor`, `hardware_model`, `hardware_site`, `hardware_slot` and never `netops_alert`;
5. one **stale trigger** per source (`nodata`, default 15m) tagged `hardware_component=sensor_stale` - *the device or SNMP is not answering*, which is **not** a fan/PSU fault and is worded as such.

Status classes come from the vendor's documented enumeration. **No threshold is invented**: temperature alerts exist only where the device reports its own state (Cisco IOS ENVMON); Huawei/PAN/Nexus temperature are readings or sensor-health only. See `docs/VENDOR-COVERAGE.md`.

## Offline commands (no Zabbix needed)
```bash
H="python3 hardware_audit.py"
$H vendors list | coverage | simulate | messages | check
$H template build --definition cisco-iosxe --out cisco-iosxe.json       # the import file
$H template check --definition cisco-iosxe                                # structural import check
```
`simulate` runs the *generated* expressions against normal / fault / single-glitch / recovery / recovery-flap / wrong-state / stale series.

## Deploying a template to the LAB (guarded, reversible)
```bash
$H --env lab template plan  --definition cisco-iosxe     # create | update | noop | CONFLICT
$H --env lab template apply --definition cisco-iosxe     # backup first, import, read back; never links to a host
$H --env lab template rollback --definition cisco-iosxe
```
A same-named template without this tool's ownership marker + definition id is a CONFLICT and is never touched. Updates re-read the live template just before writing. Rollback restores the exact earlier export, or deletes a tool-created template only if it is linked to no host.

## Putting a device under monitoring (operator steps; the tool does not do these)
1. Host with an SNMP interface (v2c/v3) in Zabbix; link `NETOPS-HW <definition>`.
2. Host macros (**mandatory for readable alerts**): `{$NETOPS.HW.MODEL}` (exact model, e.g. `Catalyst 9300-48P`), `{$NETOPS.HW.SITE}`. PAN-OS also: `{$NETOPS.HW.API.URL}`, `{$NETOPS.HW.API.USER}`, `{$NETOPS.HW.API.PASSWORD}` (**secret** macro; never in Git).
3. Wait one discovery interval; check Latest data shows concrete per-sensor items with plausible values.
4. **Record real-device evidence** (raw walk output, model, software version) and only then add the host to `config/hardware.<env>.yaml` and `config/device-evidence.yaml`. Until a device is verified the matrix says SIMULATED TESTED at most.
5. Run `audit` - PASS needs a fresh concrete item, a verified status mapping, and a bound enabled trigger with the dedicated tags.

## Reading alerts
* `Component: fan slot <sensor name>` + `Vendor` / `Model` / `Site` identify the part. The Problem subject is `[HARDWARE PROBLEM] <definition>: <what> on <host>`.
* `sensor_stale`: check reachability/SNMP/credentials first; nothing is known about the hardware.
* A Problem with severity High (`failed`) vs Warning (`degraded`) is the vendor's own severity class, not ours.

## What this tool will not do
Enable the Hardware action, create media types/user groups, touch Interface Alerting, write to Production, or modify any object it cannot prove it owns.

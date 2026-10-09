# Claude -> Codex: Hardware Health remediation hand-off

Branch `claude/hardware-health-remediation`, based on your discovery commit `281361c`. The exact candidate commit is stated in the final report / the branch history (`git log -1` of the commit that adds this file's parent).

## What changed

All 11 audit findings and implications in your report are fixed or implemented, each with a regression test: see [AUDIT-CORRECTIONS.md](AUDIT-CORRECTIONS.md). In addition: server-side identity validation, the four-vendor coverage matrix, the vendor catalogue, the (empty) verified-status registry, and the separate disabled NETOPS-HW action tooling ([NOTIFICATION-ACTION.md](NOTIFICATION-ACTION.md)).

Untouched: `zabbix-alerting/` (Interface Alerting v1.0.2) - byte-identical to the base commit; the approved LAB and Production hardware inventories (`hosts: {}`); Zabbix itself (nothing was written anywhere; all validation was offline).

## Please run (LAB, read-only unless stated)

```bash
cd zabbix-hardware-health
python3 -m unittest discover -s tests -t .                 # expect 96 tests OK (Python 3.9+, PyYAML)
export ZABBIX_HARDWARE_URL_LAB=... ZABBIX_HARDWARE_TOKEN_LAB=...     # a dedicated read-only token if you can
python3 hardware_audit.py --env lab discover --host DR-FW01 --host DR-LEAF01 --host <one IOSv>   # compare raw_input_count / candidates with your own findings
python3 hardware_audit.py --env lab audit                  # exit 3 "No approved hosts" is still correct
python3 hardware_audit.py --env lab action plan            # read-only; needs config/notifications.lab.yaml (copy the example, existing media type + group names)
```

Things I could not verify offline and need your eyes on:

1. **Real API shapes**: `item.get` with `selectValueMap` / `selectPreprocessing` / `selectTags` and the `valuemap` property name; `host.get` with `selectInventory` and `selectInterfaces[available]`; `trigger.get` with `expandExpression` + `selectItems`; `usermacro.get` with `globalmacro`. A shape difference would show as a KeyError/empty field in `discover` output - report it and I will fix `tests/fakes.py` first.
2. **Raw-input detection** against your seven IOSv hosts: expect `raw_input_count` 3 each (fans/psu/temp walks) and `candidate_sensor_count` 0.
3. **Action filter semantics**: condition type 26 equals, type 25 *does not equal* on tag name `netops_alert` (my reading of the Zabbix 7.0 docs; your report recommended the same). HW-N1..N6 in NOTIFICATION-ACTION.md settle it. `action apply` is LAB only and creates a **disabled** action; do not enable it by hand except inside HW-N4.
4. Macro names in the message templates (`{EVENT.TAGS.hardware_*}`, `{INVENTORY.MODEL}`) - unresolved macros print as `*UNKNOWN*` and need a delivery test.

## Blockers I cannot remove from here

* No real devices for any of the four vendors (see VENDOR-GAPS-AND-TEST-DEVICES.md): every vendor cell is GAP or BLOCKED.
* LAB router management addresses were unreachable from the Zabbix VM at your discovery; real SNMP data needs reachability first.
* No verified vendor status mappings (needs a device capture + MIB/API documentation per vendor).
* Mechanism for tagging hardware triggers (template vs clone) is an open design decision that needs a real device to vet triggers.
* Delivery of Problem/Recovery has not been tested; the action stays disabled.

Nothing in this branch claims hardware coverage or notification readiness.

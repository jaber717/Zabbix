# Independent LAB acceptance — Hardware Health v0.2

Candidate tested: `946dd0be88a3b784e1b527a43de4f544bc7bca03` (detached, dedicated worktree). Zabbix: real LAB 7.0.30 on RHEL 9.6. No Production, device, trigger, action, or Interface Alerting write was made. The live API probe is `qa/live_api_shape_probe.py`; it prints shapes and counts, never credentials or values.

## Compatibility and safety

| Gate | Evidence | Result |
|---|---|---|
| Runtime | `python3 --version` = 3.9.21; installed `python3.12 --version` = 3.12.9. Python 3.12 lacked PyYAML in its system site-packages. A temporary 3.12 venv installed only `requirements.txt` (`PyYAML>=6,<7`). No system Python was changed. | Python 3.12 usable with declared dependency |
| Automated tests | `/tmp/.../py312/bin/python -m unittest discover -s tests -t .` | 96/96 PASS |
| Python syntax | 3.12 `compileall -q hardware_audit.py hwh tests qa` | PASS |
| Bash syntax | No `*.sh` exists in `zabbix-hardware-health/`. | NOT APPLICABLE; not a PASS claim |
| Secret patterns | 33 tracked Hardware Health files plus the QA probe scanned for private keys, GitHub/Telegram/Bearer/Zabbix tokens and secret assignments; only finding counts were printed. | 0 findings |
| Interface Alerting | `git diff --quiet v1.0.2 946dd0b -- zabbix-alerting` exited 0. | Byte-identical to v1.0.2 tag |
| API writes | Probe `writes_made []`; only discover, audit, and action **plan** were invoked. | 0 |

The initial direct 3.12 test attempt failed during import because its system environment had no PyYAML; that attempt did **not** run 96 tests and is not counted as a PASS. The subsequent isolated 3.12 venv run passed. The default `python3` remains 3.9.21, so deployment commands that must use 3.12 should invoke `python3.12` or a 3.12 venv explicitly. No 3.9 installation is needed.

## Real API contract

`apiinfo.version` returned `7.0.30`. `usermacro.get` with `globalmacro: true` returned exactly one `{$NETOPS.ENVIRONMENT}` row with `value=lab`. Calling the identity verifier with a deliberately wrong `production` claim refused it with `IDENTITY MISMATCH`, before host reads.

The read-only shape probe against `PNET-SITE-A`, `DR-FW01`, and `DR-LEAF01` confirmed:

- `host.get` returns `host,hostid,status,interfaces,inventory,parentTemplates`. `selectInventory` returned an empty **list** on these unpopulated hosts; `selectInterfaces` and `selectParentTemplates` returned lists. The candidate handles the empty inventory list.
- `item.get` returned `lastvalue,lastclock,snmp_oid,units,value_type,state,status,preprocessing,tags,valuemap`. `selectValueMap` produced a populated **dict** on some items and `[]` where absent; `selectPreprocessing` and `selectTags` returned lists. The candidate handles both value-map shapes.
- `trigger.get` accepted `expandExpression: true`, `selectItems`, and `selectTags`; it returned `expression,items,tags` plus requested trigger fields. No parse/KeyError was seen.
- `action.get` returned the live Interface Alerting filter as `conditiontype=25, operator=0, value=netops_alert`; its action remained enabled and unmodified.

These are LAB API-shape checks, not proof of hardware monitoring. No API response-format defect was reproduced.

## Coverage, by independent dimension

| Dimension | Live result |
|---|---|
| Telemetry coverage | **0 verified physical sensors.** Seven Cisco IOSv hosts each had three raw environmental walks (fan, PSU, temperature), all `lastclock=0`. Each had zero concrete environmental candidates and an unavailable SNMP interface. `raw_input_count=12` on SITE-A includes other raw inputs; the three environmental walks are a subset. The handoff's expected total of 3 is therefore too narrow, but the concrete exclusion works. |
| Alert coverage | No validated, dedicated-tag hardware trigger tied to a fresh physical sensor. FortiGate mock `DR-FW01` exposed seven HA-name **candidates** with `lastclock=0`, not fan/PSU redundancy or validated HA telemetry. No hardware action existed. |
| Notification readiness | **NOT READY / delivery NOT TESTED.** The existing Telegram media type is enabled, but there is no approved recipient group/configuration and no real hardware event. No Problem or Recovery notification was claimed. |

Vendor status: Cisco IOSv raw inputs are not physical readings; Nexus hosts are mock/unavailable; no ASR live host was available. Palo Alto and Huawei have no monitored LAB host; Fortinet's DR-FW01 is an unavailable mock. None can be approved for the Hardware Health inventory. `config/hardware.lab.yaml` correctly remains `hosts: {}`. Running the approved `audit` returned exit 3, `No approved hosts in inventory. Audit not run.`

A separately labeled **unapproved diagnostic** policy declared an existing DR-FW01 HA item solely to exercise the live unreachable path. It was not added to either inventory. The report had `identity_verified=true`, `unreachable=true`, overall/category/sensor `BLOCKED`, reason `HOST_UNREACHABLE`, and no fabricated state (exit 2 for incomplete coverage). HA and hardware redundancy remained distinct.

For a *reachable* host with a fresh interpretable sensor but no trigger, `verify_sensor()` retains the value in `current_state` and returns `NO_TRIGGER`/`GAP`; it does not say the sensor is absent. The current summary/matrix nevertheless has only a combined coverage verdict, not explicit `telemetry_coverage` and `alert_coverage` fields. Claude should expose both dimensions separately before a real sensor is approved.

## Read-only action plan and exact handoff defects

Using the shipped `config/notifications.example.yaml`, the 3.12 live plan exited 1: `Network Operations` user group does not exist in this LAB. The available group `Zabbix administrators` was used **only in a temporary plan input**, not as an approved notification recipient. That plan exited 0 and proposed `CREATE action 'NETOPS-HW Hardware Health' (disabled)`; its seven-event crossover model found zero wrong routes. `--enable` was refused because Problem delivery, Recovery delivery, interface exclusion, and validator evidence are absent. No action was created.

1. **Recipient configuration (live reproduction):** `python3.12 hardware_audit.py --env lab action plan --notifications config/notifications.example.yaml` returns the missing-group conflict above. Select and approve a real LAB recipient group before any apply; do not silently route to administrators based on this diagnostic.
2. **Message macro syntax (source-level defect to fix before delivery):** `hwh/action.py` uses `{EVENT.TAGS.hardware_model}`, `{EVENT.TAGS.hardware_vendor}`, `{EVENT.TAGS.hardware_site}`, `{EVENT.TAGS.hardware_component}`, and `{EVENT.TAGS.hardware_slot}`. Zabbix 7.0 documentation says tag names with non-alphanumeric characters should be double-quoted inside this macro, so these underscore-bearing names should use the documented quoted form, e.g. `{EVENT.TAGS."hardware_model"}`. The API accepts template text without expanding it; a real delivery or isolated macro test is still required. `{INVENTORY.MODEL}` is documented, but these LAB hosts have empty inventory, so it cannot supply their model here.
3. **Unreachable vs missing distinction:** when a declared item exists and all polling interfaces are unavailable, the live test returns `BLOCKED/HOST_UNREACHABLE`. `verify_sensor()` currently returns `GAP/ITEM_MISSING` *before* checking `unreachable` when the declared item is absent, and returns `GAP/STALE` for a stale item on a host whose interface still reports available. Confirm the intended policy for missing/stale SNMP; do not call these a physical fault or HEALTHY.
4. **Handoff expectation:** `raw_input_count` counts all raw inputs, not only fan/PSU/temperature. SITE-A's observed total was 12, while exactly three were environmental walks. Change the expected count or report an environmental subset explicitly; the corrected sensor exclusion itself passed.

Zabbix 7.0 references: [supported macros](https://www.zabbix.com/documentation/7.0/en/manual/appendix/macros/supported_by_location), [action conditions](https://www.zabbix.com/documentation/7.0/en/manual/config/notifications/action/conditions), [action API object](https://www.zabbix.com/documentation/7.0/en/manual/api/reference/action/object).

## Next safe validation

With approved LAB recipients, a dedicated temporary trapper item and trigger on an isolated LAB host could carry `netops_hardware=1` and a valid `hardware_component` tag. A controlled Problem then Recovery, followed by deletion/restoration, can test the notification pipeline and exclusion from Interface Alerting. Require an approved isolated test scope first. Even if delivered, label it **NOTIFICATION PIPELINE PASS**, never physical Hardware Health PASS. Real vendor sensor mappings and trigger semantics still require actual devices.

# Independent read-only LAB acceptance — Hardware Health v0.2.1

Candidate: `fa66e3daa4baeb1a88f20c189e8af3efd0142dea`, checked out detached in a dedicated worktree and independently cloned at that SHA on the LAB VM. This evidence used the real Zabbix 7.0.30 API on RHEL 9.6. There were **no Zabbix API writes**, no synthetic events, no Telegram alerts, no Production access, and no Interface Alerting changes.

## Candidate gates

| Gate | Result |
|---|---|
| Python runtime | Installed `python3.12` is 3.12.9; an isolated temporary 3.12 venv installed only the declared `PyYAML>=6,<7`. No system Python was changed. |
| Tests | `python -W error::ResourceWarning -m unittest discover -s tests -t .`: **125/125 PASS**. |
| Python syntax | 3.12 `compileall -q hardware_audit.py hwh tests qa`: PASS. |
| Bash syntax | NOT APPLICABLE: no Hardware Health `*.sh` files exist. |
| Secret scan | 37 tracked Hardware Health files checked for private keys, GitHub/Telegram/Bearer/Zabbix tokens and secret assignments: 0 pattern findings. No matching value was printed. |
| Interface Alerting | `git diff --quiet v1.0.2 fa66e3d -- zabbix-alerting` exited 0: byte-identical to its v1.0.2 tag. |
| Approved LAB inventory | `config/hardware.lab.yaml` remains `hosts: {}`; the approved audit correctly exits 3, `No approved hosts in inventory. Audit not run.` |

## Live API and coverage checks

- `apiinfo.version=7.0.30`; `usermacro.get(globalmacro=true)` returned exactly one `{$NETOPS.ENVIRONMENT}=lab`. A deliberately wrong `production` identity claim was refused. `host.get`, `item.get` with value-map/preprocessing/tag selects, and `trigger.get` with expanded expression/item/tag selects returned the expected shapes; there was no parse exception.
- Live discovery on `PNET-SITE-A`: `raw_input_count=12`, `environmental_raw_input_count=3`, all three environmental raw walks unsampled (`lastclock=0`), `candidate_sensor_count=0`, SNMP reachability `unreachable`. The raw walks are not counted as concrete sensors.
- `DR-FW01`: 8 raw inputs, one classified environmental; seven HA-name candidates, none fresh/supported for a coverage claim, and the host is unreachable. HA is kept separate from fan/PSU hardware redundancy. `DR-LEAF01`: zero raw inputs and zero sensor candidates; unreachable.
- A temporary **unapproved diagnostic policy**, never added to either approved inventory, declared one existing DR-FW01 HA item to exercise the read-only audit. Schema 3 reported `telemetry_summary={BLOCKED:1}`, `alert_summary={NOT_EVALUATED:1}`, `notification_readiness=NOT_READY`, `delivery_tested=false`, `action_exists=false`. The sensor reason was `HOST_UNREACHABLE` and `current_state=null`; no hardware fault or healthy state was invented.
- Missing declared item is deliberately `GAP/ITEM_MISSING` (configuration fact even when a device is down). An existing item on an unreachable host is `BLOCKED/HOST_UNREACHABLE`. A stale item on a reachable host is `GAP/STALE` and `current_state=null`; an unsupported item is `GAP/ITEM_UNSUPPORTED` before value interpretation. These paths are covered by the passing tests. None is a physical fan/PSU fault.
- A fresh interpretable sensor without a dedicated trigger is represented as `telemetry_coverage=PASS`, `alert_coverage=GAP`, not as an absent sensor. `notification_readiness` is calculated separately from both and remains `NOT_READY` in the LAB.

No physical sensor is approved for Cisco, Palo Alto, Fortinet, or Huawei. The existing LAB hosts do not establish physical vendor/model mappings, and the empty inventory must remain empty.

## Hardware action — read-only review

`action.get` showed the live enabled `NETOPS-IaC Interface Alerts` action still filters on event-tag name `netops_alert` (`conditiontype=25`, `operator=0`). No `NETOPS-HW Hardware Health` action exists. The candidate's proposed trigger-action filter is an AND (`evaltype=1`) of `netops_hardware=1` (tag-value condition 26, equals) and absence of tag `netops_alert` (tag-name condition 25, does-not-equal). That matches the documented Zabbix 7.0 condition meanings; its event-routing simulation passed offline, but no action was applied and live event delivery is unverified. [Zabbix 7.0 action conditions](https://www.zabbix.com/documentation/7.0/en/manual/config/notifications/action/conditions).

The source-generated Problem and Recovery templates use quoted tag macros such as `{EVENT.TAGS."hardware_model"}`; no unquoted underscore-bearing payload tag macro remains. This matches the documented tag-name quoting rule, but **actual macro expansion is NOT VERIFIED** without delivery. [Zabbix 7.0 supported macros](https://www.zabbix.com/documentation/7.0/en/manual/appendix/macros/supported_by_location).

Recipient approval fails closed: the shipped example has blank media type, groups, approver and reference; `action plan --notifications config/notifications.example.yaml` exited 3 with a missing-recipient conflict. No `config/notifications.lab.yaml` exists, so the default plan also exited 3 rather than selecting administrators or another group. A complete live action plan cannot be approved until the operator names and approves actual recipients. Telegram media type is enabled, but this is not hardware notification readiness. No action was created or enabled.

## Synthetic-test correction and safety review for Claude

The approval form in `docs/SYNTHETIC-NOTIFICATION-TEST.md` says cases A/B/C mean **six messages**. Correct expectation, **per approved recipient**, is:

| Case | Expected hardware-action messages | Other-action exposure |
|---|---:|---|
| A: tagged Problem then Recovery | 2 (one Problem, one Recovery) | 0 from Interface Alerting |
| B: stock-style tags, Problem then Recovery | 0 | 0 |
| C: value with no trigger | 0 | 0 |
| D: optional cross-tagged Problem then Recovery | 0 | The plan expects an Interface Alerting Problem and Recovery per its recipients; verify its live recovery operation and obtain separate explicit approval first. |

Thus A/B/C total **two** hardware notifications per approved recipient, not six. For multiple recipients, total delivered messages scale with recipient count; do not promise two globally. Fix the approval form before requesting consent. D must remain excluded unless Interface Alerting recipients and extra message volume are separately approved.

The cleanup sequence (disable action; delete test triggers, item, host, group; roll back action from backup; verify absence and Interface Alerting equality) is sensible, and the plan correctly states that event history and delivered messages cannot be undone. Before any future test, additionally fail if the `NETOPS-HW-SYNTH*` namespace already contains objects, record exact created IDs, and delete **only those IDs**. Do not delete by prefix; avoid removing another operator's pre-existing fixture. Verify every readback after cleanup. No fixture or rollback operation was performed in this acceptance run.

## Decision

**APPROVED WITH LIMITATIONS for the read-only v0.2.1 source candidate.** Python 3.12 and live API compatibility passed. The action, recipient selection, macro expansion, and delivery are not accepted for operation. Correct the synthetic message-count form and tighten ID-scoped cleanup before seeking explicit approval for a separate synthetic delivery test. Physical hardware monitoring remains unvalidated until real sensor values and vendor semantics are evidenced.

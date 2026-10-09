# LAB synthetic notification test procedure (HW-N4 / HW-N6, optional HW-N5)

**NOT EXECUTED. Requires explicit written approval before any step. LAB only.** Nothing in this repository performs these steps; they are carried out by the independent tester with a LAB token that may write hosts, triggers and actions.

## What this test can and cannot prove

| Can prove | Cannot prove |
|---|---|
| The separate action `NETOPS-HW Hardware Health` delivers one Problem and one Recovery message to the approved recipients with the intended content, including the quoted `{EVENT.TAGS."..."}` macros | That any real fan, PSU, temperature or HA sensor is monitored or that a vendor status code means what a trigger assumes |
| Events without the dedicated tags are not delivered by this action | Physical Hardware Health coverage (the matrix stays 0 PASS) |
| The Interface Alerting action does not deliver a hardware-tagged event | Production readiness |

If it succeeds, the only permitted label is **NOTIFICATION PIPELINE PASS (synthetic)**. It is never "Hardware Health PASS".

## 0. Approval record (fill in BEFORE starting; no approval, no test)

```text
Approved by: ____________   Reference: ____________   Date/time window (Asia/Riyadh): ____________
Approved recipient group(s) (exact names): ____________      Approved media type (exact): ____________
Message volume accepted: exactly 1 Problem + 1 Recovery per test case (cases A, B, C = 6 messages; D optional +1)
Tester: ____________     Rollback owner: ____________
```

The recipients go into `config/notifications.lab.yaml` (`usergroups`, `approved_by`, `approval_reference`). They are never defaulted, and the Zabbix administrators group is not a substitute for an unapproved choice.

## 1. Preconditions (read-only checks)

1. `hardware_audit.py --env lab action plan` shows `CREATE ... (disabled)`, 0 conflicts, crossover model 0 wrong.
2. LAB identity macro `{$NETOPS.ENVIRONMENT}` = `lab` (the tool already checks).
3. `trigger.get` filtered by tag `netops_hardware` returns **nothing** (no other trigger can fire through the action during the window).
4. Note the current state of every object that will be touched: the Interface Alerting action (must stay untouched and enabled), the NETOPS-HW action (absent), and the list of recent problems.
5. Telegram/e-mail recipients know a test is running.

## 2. Create the synthetic fixtures (isolated, clearly named, all deletable)

Created by the tester with the API; every object name starts with `NETOPS-HW-SYNTH`.

| Object | Definition |
|---|---|
| host group | `NETOPS-HW-SYNTH` |
| host | `NETOPS-HW-SYNTH-01`, in that group, **no interfaces**, no templates, monitored |
| item (trapper) | key `netops.hw.synthetic.state`, type trapper (2), numeric unsigned, no preprocessing |
| trigger A (hardware, correct tags) | expression `last(/NETOPS-HW-SYNTH-01/netops.hw.synthetic.state)=1`, severity Average; tags `netops_hardware=1`, `hardware_component=fan`, `hardware_vendor=synthetic`, `hardware_model=SYNTHETIC-NOT-A-DEVICE`, `hardware_site=LAB`, `hardware_slot=synthetic-1` |
| trigger B (stock-style, must not notify) | expression `last(/NETOPS-HW-SYNTH-01/netops.hw.synthetic.state)=2`, tags `scope=availability`, `component=fan` only |
| trigger C (mis-tagged, must not notify via this action) | expression `last(...)=3`, tags `netops_hardware=1` **and** `netops_alert=synthetic_test` - **see the HW-N5 warning: this one also matches the Interface Alerting action** |

Create trigger C only if case D is separately approved.

## 3. Create the action (disabled) with the tool

```bash
cp config/notifications.example.yaml config/notifications.lab.yaml    # fill in the APPROVED values only
python3.12 hardware_audit.py --env lab action plan
python3.12 hardware_audit.py --env lab action apply                  # creates 'NETOPS-HW Hardware Health', DISABLED; note the printed backup path
```

## 4. Enable for the test window only

The tool will (correctly) refuse `--enable`: the validation record is still all-false. Enabling for the window is therefore a **manual, approved change by the tester** in the Zabbix UI or API (`action.update` status 0 on the `NETOPS-HW Hardware Health` action only). Record the time. The tool's `config/action-validation.yaml` is filled in only after the evidence below exists.

## 5. Cases (values are sent with `zabbix_sender` from the LAB Zabbix host to host `NETOPS-HW-SYNTH-01`)

| Case | Action | Expected | Evidence |
|---|---|---|---|
| A. Problem | send value `1` | trigger A fires; exactly **one** hardware Problem message to the approved recipients; subject `[HARDWARE PROBLEM] ...`; body shows host, severity, date/time, event ID, and resolved `Model/Vendor/Site/Component/slot` values (`SYNTHETIC-NOT-A-DEVICE`, `synthetic`, `LAB`, `fan`, `synthetic-1`) - **no literal `*UNKNOWN*`** | message screenshot/text, event ID, alert history row |
| A. Recovery | send value `0` | trigger A recovers; exactly one Recovery message with recovery date/time and duration | same |
| B. Stock-style tags | send `2`, then `0` | event appears in Monitoring -> Problems; **no** message from this action; no message at all | alert history shows none |
| C. Unknown value | send `5` | nothing fires (no trigger matches) - sanity | none |
| D. (optional, separate approval) tags on both families | send `3`, then `0` | the hardware action sends **nothing**. **Warning:** the Interface Alerting action will legitimately deliver one interface-style message and one recovery to its own recipients, because the event carries `netops_alert`. Warn those recipients first. | alert history for both actions |

Failure criteria (stop at once, go to section 6): a message from this action for case B/C/D; more than one Problem or Recovery message; an unresolved macro (`*UNKNOWN*`) in the body; a message to anyone outside the approved recipients; any change in the Interface Alerting action; a delivery error/retry in the alert history.

If `*UNKNOWN*` appears for the `{EVENT.TAGS."..."}` values, record the exact rendered text. That is a macro-syntax finding to hand back to the developer, not a reason to improvise another syntax live.

## 6. Roll back (always, pass or fail)

1. Disable the NETOPS-HW action (manual, restoring `status=1`) and confirm in the UI.
2. Delete trigger(s), item, host, host group (in that order) - verify `trigger.get`/`host.get`/`hostgroup.get` return none of the `NETOPS-HW-SYNTH*` objects.
3. `python3.12 hardware_audit.py --env lab action rollback --backup state/backups/hardware-action-lab-<stamp>.json` - removes the action this tool created (or restores the previous definition if one existed).
4. Verify: `action plan` shows `CREATE` again (the action is gone), the Interface Alerting action is byte-identical to the note taken in step 1.4, no trigger carries `netops_hardware`.
5. Problem/event history rows created by the test remain in Zabbix history (events cannot be deleted); they are identifiable by the host name and are documented in the evidence.

Rollback is reversible and complete except for those history rows and the messages already delivered.

## 7. Record the result

Only after cases A and B (and C/D if approved) are evidenced, and rollback verified, fill in `config/action-validation.yaml` **truthfully**:

* `problem_delivery`, `recovery_delivery`: verified true with the evidence reference **for the synthetic pipeline**;
* `interface_exclusion`: true only if case D was run; otherwise leave false and say so;
* `validated_by`.

Even then: a synthetic result does not make the action ready for real devices. Hardware coverage stays 0 PASS until real sensors with verified status mappings and dedicated-tag triggers exist (see VENDOR-GAPS-AND-TEST-DEVICES.md). Report the outcome as `NOTIFICATION PIPELINE PASS (synthetic)` or `FAIL` with the failing criterion.

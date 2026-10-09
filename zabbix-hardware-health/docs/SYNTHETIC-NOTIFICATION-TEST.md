# LAB synthetic notification test (HW-N4 / HW-N6)

**NOT EXECUTED. Needs explicit written authorization from the operator before any Zabbix write. LAB only. No Production, no Interface Alerting change.**
Nothing in this repository writes to Zabbix for this test. The tooling added for it (`hardware_audit.py --env lab synthetic ...`) is **read-only against Zabbix** (review, preflight, snapshot, diff, cleanup-plan, verify) plus two commands that write only a local ledger file (`ledger-record`, `ledger-mark`). The fixtures are created and deleted by the independent tester with an approved LAB token.

## 1. Three results that must never be confused

| Label | Meaning | Status today |
|---|---|---|
| **AUDIT PASS** | the read-only audit (`hardware_audit.py audit`) found declared sensors readable, mapped and trigger-bound | not achieved: the approved inventory is empty (`hosts: {}`), no real sensor is verified |
| **NOTIFICATION PIPELINE PASS (synthetic)** | the separate action delivered one Problem and one Recovery with expanded macros for a synthetic event, and did not act on unrelated events | this test; not yet run |
| **REAL HARDWARE COVERAGE PASS** | real fan/PSU/temperature/redundancy/HA sensors on real vendor devices, verified status mappings, dedicated-tag triggers, real or safely simulated state changes delivered | not achieved; needs real devices (VENDOR-GAPS-AND-TEST-DEVICES.md) |

A synthetic pass proves the plumbing only. It must be reported as `NOTIFICATION PIPELINE PASS (synthetic)`, never as hardware coverage and never as production readiness.

## 2. Expected notifications - per approved recipient

"Recipient" = a user in an approved user group who has an enabled medium of the approved media type. Totals scale with the number of recipients; they are not a fixed number.

| Case | What is sent to the trapper item | Hardware-action messages | Interface Alerting exposure |
|---|---|---|---|
| **Case A** - hardware-tagged trigger | `1` then `0` | **1 Problem + 1 Recovery per approved recipient** (2 per recipient) | none |
| **Case B** - stock-style tags (`scope`, `component` only) | `2` then `0` | **zero** hardware notifications (the event shows in Problems only) | none |
| **Case C** - value no trigger matches | `5` | **zero** notifications of any kind | none |
| **Case D** - tagged for both families | `3` then `0` | zero from the hardware action | **Case D is excluded from the default test.** It would produce an Interface Alerting Problem and Recovery for that action's recipients. It needs its own approval (`case_d`), including confirmation that those recipients were told |

Default test = A + B + C = **2 hardware messages per approved recipient in total** (all from Case A). Example: two approved recipients -> 4 messages.

## 3. Authorization record (no fallback of any kind)

Copy `config/synthetic-test.example.yaml` to `config/synthetic-test.yaml`. The operator fills in **every** field; a blank or missing field makes `synthetic preflight` refuse:

* `approved_by`, `approval_reference`
* `window_start`, `window_end` (ISO-8601 with offset; at most 4 hours)
* `media_type` and `usergroups` - exact existing names, and **identical** to `config/notifications.lab.yaml` (one approval, one source of truth). There is no default recipient and the Zabbix administrators group is never substituted.
* `test_scope`: the fixed namespace `NETOPS-HW-SYNTH` / `NETOPS-HW-SYNTH-01` and the list of cases (default `[A, B, C]`).
* `case_d` (approver, reference, `interface_recipients_notified: true`) only if D is listed.
* `existing_hardware_action` (acknowledged, note) only if a disabled hardware action already exists.

## 4. Readiness review (any time) and preflight (the execution gate)

The approved window is a **mandatory execution gate**, not a hint.

```bash
python3.12 hardware_audit.py --env lab synthetic review      # read-only; may run BEFORE the window; reports READY / NOT READY; never authorises execution
python3.12 hardware_audit.py --env lab synthetic preflight   # the gate: refused outside the approved window (before any server is contacted) and on any failed check
```

* `review` runs every readiness check below but treats the window as informational. READY means "the lab looks clean and the approval is complete"; it is never permission to start.
* `preflight` is **refused outside the approved window**. The same gate also guards `ledger-record` and `ledger-mark --event enabled`, so no fixture can be recorded and the action cannot be marked enabled outside the window. Winding down (`ledger-mark --event disabled`, `cleanup-plan`, `snapshot`, `diff`, `verify`) is deliberately never gated.

Both refuse if any of the following is false: scope complete; scope recipients equal the action configuration; the approved media type exists **and is enabled** and the approved user group(s) exist with at least one user who would receive messages; **the synthetic namespace is empty** - no host group `NETOPS-HW-SYNTH`, no host `NETOPS-HW-SYNTH-01`, no item `netops.hw.synthetic.state` on any host, no trigger whose name starts `[NETOPS-HW-SYNTH] `; no trigger anywhere already carries `netops_hardware`; the hardware action is absent or **disabled**; at least one Interface Alerting (`NETOPS-IaC`) action exists to snapshot.

**A pre-existing hardware action is never silently adopted.** If one exists (it must be disabled), the approval record must contain `existing_hardware_action: {acknowledged: true, note: ...}`; otherwise preflight refuses. With the acknowledgement the test does **not** run `action apply` (which would modify it), records it in the ledger *without* `--created-by-test`, and cleanup never deletes or rolls it back; the after-manifest must show it byte-identical.

## 5. Before manifest

```bash
python3.12 hardware_audit.py --env lab synthetic snapshot --out evidence/synth-before.json
```

The manifest holds, for every Interface Alerting action: id, name, status and a SHA-256 of its full definition (ids stripped) plus the definition itself; for the hardware action: existence, id, status, its **full signature** (filter conditions, evaluation type, recipient group ids, media type, Problem and Recovery subject/message, operation counts) and a SHA-256 of its whole definition; the (empty) synthetic object lists; the count of `netops_hardware` triggers; the recipient user ids; and a manifest hash.

## 6. Create fixtures and RECORD EVERY ID

The tester creates, with the approved LAB token, in this order: host group `NETOPS-HW-SYNTH`; host `NETOPS-HW-SYNTH-01` (no interfaces, no templates); trapper item `netops.hw.synthetic.state` (unsigned numeric); trigger A `[NETOPS-HW-SYNTH] case A hardware-tagged` (`last(...)=1`, Average, tags `netops_hardware=1`, `hardware_component=fan`, `hardware_vendor=synthetic`, `hardware_model=SYNTHETIC-NOT-A-DEVICE`, `hardware_site=LAB`, `hardware_slot=synthetic-1`); trigger B `[NETOPS-HW-SYNTH] case B stock-style tags` (`last(...)=2`, tags `scope=availability`, `component=fan`); trigger D only if approved (`last(...)=3`, tags `netops_hardware=1` and `netops_alert=synthetic_test`). Case C has no trigger.

**Immediately after each create call**, write the exact id returned into the ledger (a local file, mode 0600, Git-ignored):

```bash
L=state/synthetic/ledger-<approval_reference>.json
python3.12 hardware_audit.py --env lab synthetic ledger-record --ledger $L --kind hostgroup --id <id>
python3.12 hardware_audit.py --env lab synthetic ledger-record --ledger $L --kind host      --id <id>
python3.12 hardware_audit.py --env lab synthetic ledger-record --ledger $L --kind item      --id <id>
python3.12 hardware_audit.py --env lab synthetic ledger-record --ledger $L --kind trigger   --id <id> --case A
python3.12 hardware_audit.py --env lab synthetic ledger-record --ledger $L --kind trigger   --id <id> --case B
```

Then create the hardware action (disabled) with the tool and record it:

```bash
python3.12 hardware_audit.py --env lab action apply            # prints the backup path; creates 'NETOPS-HW Hardware Health', DISABLED
python3.12 hardware_audit.py --env lab synthetic ledger-record --ledger $L --kind action --id <action id> --created-by-test
```

## 7. Temporary enablement - an explicitly approved test exception

The action is **disabled at all times outside the approved test window**. The tool correctly refuses `--enable` because `config/action-validation.yaml` is all-false; that gate is not bypassed. Enabling for the test is a separate, manual, approved exception made by the tester on the recorded action id only.

For Cases B and C to prove that filtering works, the action must be live while they run. It is therefore **kept enabled through Cases A, B and C**, inside the window:

1. enable the recorded action once, before Case A (`ledger-mark --event enabled`, which is itself window-gated);
2. run Cases A, B and C (and D only if separately approved) with the action still enabled;
3. **immediately after the last case**, set the recorded action back to disabled and `ledger-mark --event disabled`; confirm in the UI.

**On any failure** (section 8) disable the action at once - do not finish the remaining cases first. `verify` prints the instruction on a failure, and `cleanup-plan` always begins with the disable step whenever the recorded action is enabled on Zabbix. B and C results are only accepted when Case A's Problem was delivered by the same action (a positive control), because a zero is meaningless from an action that was not live.

## 8. Run the cases, then verify (read-only)

Send the values with `zabbix_sender` from the LAB Zabbix host to host `NETOPS-HW-SYNTH-01`, key `netops.hw.synthetic.state`, and wait for the trigger/alert processing between values.

```bash
python3.12 hardware_audit.py --env lab synthetic verify --ledger $L --case A    # also B, C (and D only if approved)
```

`verify` checks, using only event/alert/action reads:

* **Problem and Recovery** - exactly one Problem event for the case trigger, recovered; Case A: each approved recipient has exactly one Problem alert and one Recovery alert from the hardware action (`p_eventid` distinguishes them), nobody else, all delivered (`status` sent, no `error`);
* **Message macro expansion** - the Problem message contains the expanded values `SYNTHETIC-NOT-A-DEVICE`, `synthetic-1`, `LAB`, `fan`; neither message contains `*UNKNOWN*` or a literal `{EVENT.TAGS`; the Recovery carries the recovery wording;
* **Alert history** - the exact alert rows (ids, users, status, retries, errors) are in the report;
* **Hardware-action exclusion** - Cases B/C: zero hardware-action alerts; across the whole action, no alert exists for any event except Case A's Problem/Recovery;
* **Interface Alerting exclusion** - no alert of any `NETOPS-IaC` action for any synthetic event (except Case D, where it is expected and checked by hand).

Stop at the first failure and go to section 9: a message from the hardware action in B/C/D, more than one Problem or Recovery per recipient, an unexpanded macro, a recipient outside the approved list, a delivery error, or any change in an Interface Alerting action. If a macro does not expand, record the exact rendered text and hand it back; do not improvise another syntax live.

## 9. Cleanup - recorded ids only, ownership-verified, never by name

```bash
python3.12 hardware_audit.py --env lab synthetic cleanup-plan --ledger $L
```

Cleanup inspects the **live** state first and prints the exact calls:

1. **FIRST STEP, always:** if the recorded hardware action id is enabled on Zabbix *right now*, disable it - regardless of what the ledger's `enabled_at` / `disabled_at` say (they may be missing or inconsistent);
2. `trigger.delete` with the **recorded trigger ids**; `item.delete`, `host.delete`, `hostgroup.delete` with the **recorded ids**;
3. if the test created the action: the tool rollback using its backup (not its name). A pre-existing action gets no deletion and no rollback.

The plan is **refused** - the tester stops and investigates, nothing is planned - if: the ledger is empty; **ownership verification fails** (every recorded id is read back and must still be the synthetic object it was recorded as: host group name, host name, item key on the recorded host, trigger description on the recorded host, action name); the synthetic namespace holds an object whose id is not in the ledger; an enabled hardware action exists that is not in the ledger; or the hardware action on Zabbix is not the recorded one. It never selects anything by name prefix, and an object already gone is simply omitted. The tester executes the printed calls with the approved token, then:

```bash
python3.12 hardware_audit.py --env lab action rollback --backup state/backups/hardware-action-lab-<stamp>.json    # only if this test created the action
python3.12 hardware_audit.py --env lab synthetic snapshot --out evidence/synth-after.json
python3.12 hardware_audit.py --env lab synthetic diff --before evidence/synth-before.json --after evidence/synth-after.json
```

`diff` must print no differences: Interface Alerting action definitions byte-identical (hash); synthetic namespace empty; the hardware action in its before-state - same existence, id and status **and the same signature and definition hash** (an unexpected change of its filter, recipients, message text or any other field is reported, as is delete-and-recreate); not left enabled; `netops_hardware` trigger count unchanged. Event and alert history rows and messages already delivered remain; they are listed in the evidence.

## 10. Recording the outcome

Fill `config/action-validation.yaml` truthfully and only from evidence: `problem_delivery` and `recovery_delivery` (for the synthetic pipeline) after Case A; `interface_exclusion` only if Case D was approved and run, otherwise leave it false and say so; `validated_by`. Report exactly one of: `NOTIFICATION PIPELINE PASS (synthetic)` or `FAIL (<criterion>)`. Hardware coverage stays at 0 PASS and the action stays disabled until real devices are validated.

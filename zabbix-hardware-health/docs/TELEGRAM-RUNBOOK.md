# Telegram integration - runbook (LAB)

**Status: NOT ENABLED. NOT DELIVERY-TESTED.** The Hardware action `NETOPS-HW Hardware Health` is created disabled and stays disabled until (1) an independent security gate passes and (2) the operator explicitly approves in writing. This tool sends no Telegram message by itself; the only thing that sends is Zabbix, through the existing LAB Telegram media type, while the action is enabled inside an approved window.

## 1. What the operator receives

Rendered by `hardware_audit.py vendors messages` from the action's real templates (so documentation and action cannot drift; a test fails if they do):

```
--- PROBLEM ---
Subject: [HARDWARE PROBLEM] <event name> on <host>
Status:      PROBLEM          Severity:    High
Host:        SW-CORE-01       Model:       Catalyst 9300-48P     Vendor: cisco
Site:        DC1              Component:   fan  slot Switch#1 Fan 1
Time:        <date> <time>    Event ID:    <id>        Tags: <all event tags>
--- RECOVERY ---
Subject: [HARDWARE RESOLVED] <event name> on <host>
Resolved:    <recovery date/time>   Duration: <duration>   + the same fields
```

Contract (checked offline): every required field present and expanded from event tags (no literal `{EVENT.TAGS`, no `*UNKNOWN*`), well under Telegram's 4096-character limit, the Problem message carries no recovery fields, and no message text references the Interface Alerting tag `netops_alert`.
`Model` and `Site` come from the host macros `{$NETOPS.HW.MODEL}` / `{$NETOPS.HW.SITE}`: **a host that does not set them produces a blank field** - the template's host-macro check in the operator guide is part of go-live.

## 2. Routing guarantees

| Event | Hardware action | Interface Alerting action |
|---|---|---|
| trigger tagged `netops_hardware=1` (all NETOPS-HW templates) | **matches** | does not match (needs `netops_alert`) |
| interface trigger tagged `netops_alert` | does not match | matches |
| trigger carrying both tag families | **excluded** (`netops_alert` does-not-equal) | matches |
| stock trigger with only `scope`/`component` tags | does not match | does not match |
| `sensor_stale` (no data) trigger | matches (it is `netops_hardware=1`) - a monitoring-quality message, not a fault | does not match |

Modelled offline (`action.crossover_report`) and re-checked live by `labsim` / synthetic `preflight`, which now also **fail if any OTHER enabled trigger action could match a hardware event** (an enabled action with no conditions matches everything; an unmodelled condition type is assumed to match - fail-closed). Duplicates: one action, one operation per recipient group and one Recovery operation; escalation is a single step (`esc_step_from=esc_step_to=1`).

## 3. Preflight (all read-only)

```bash
export ZABBIX_HARDWARE_URL_LAB=http://192.168.1.91/  ZABBIX_HARDWARE_TOKEN_LAB=<token from your secret store>
H="python3 /opt/netops-hardware-health/current/hardware_audit.py --base /opt/netops-hardware-health/current"
$H vendors messages                      # message contract
$H --env lab labsim                      # sim host/items/triggers present, delivering, no netops_alert tag, NO ENABLED ACTION matches them
$H --env lab synthetic audit-probe       # can this account read auditlog.get + history.get? (exit 4 => negative cases INCONCLUSIVE)
$H --env lab synthetic review            # readiness (any time); never authorises execution
$H --env lab action plan                 # what 'apply' would create; shows conflicts (missing media type / group, foreign action)
```
Stop and fix on any FAIL. A common one: the stock "Report problems to Zabbix administrators" action enabled - it would also notify for the test events. Disable it only through its own approved change.

## 4. Execution - two approved paths (neither is run by this release)

**Path 1 - synthetic fixtures** (`docs/SYNTHETIC-NOTIFICATION-TEST.md`): the complete, hardened procedure (approval record, window gate, ledger of exact ids, before/after manifest, cases A/B/C, authoritative-evidence `verify`, cleanup, `diff`).

**Path 2 - the existing LAB SNMP-simulator objects** (host LAB-SNMPSIM-HW-01, triggers 26409/26410/26411). They carry no hardware tags today, so they cannot reach the hardware action. This path needs two *separately approved* changes, both printed by `labsim` and never applied by it:

1. *Tag the three triggers* (additive; existing tags kept) - the `PROPOSED tag addition` in `labsim` output, applied by the operator with the approved token. The exact pre-change tags are in the `RESTORE plan` - save it first.
2. *Enable the action for a bounded window*: `action apply` (creates disabled) -> operator sets status enabled on the recorded id only, for the window -> drive Normal -> Fault -> Recovery on the simulator -> disable.

Evidence, read-only, any time afterwards:
```bash
$H --env lab labsim --evidence-since <epoch of window start>
```
Expected: per trigger, N Problems = N linked Recoveries, every alert from `NETOPS-HW Hardware Health` and none from any other action (exit 0). Anything else exits 1 with the finding.

## 5. Verification (what counts as delivered)

PASS requires *all* of: one Problem alert and one Recovery alert per approved recipient (alert status = sent, no error); the rendered message matches section 1 with real values; zero alerts from any other action; Interface Alerting definitions byte-identical before/after. **Telegram receipt by a human on the recipient chat is recorded by the operator** (Zabbix reports "sent" when the Bot API accepted it). Only then may the operator fill `config/action-validation.yaml` (`problem_delivery`, `recovery_delivery`, `interface_exclusion`, `validated_by`, each with an evidence reference) - the only way `--enable` is honoured.

## 6. Emergency disable (any time, independent of cleanup)

```bash
$H --env lab synthetic emergency-disable-plan --ledger <ledger>   # prints ONE action.update status=1 on the recorded, ownership-verified id
```
Or in the Zabbix UI: Alerts -> Actions -> `NETOPS-HW Hardware Health` -> Disabled (one click, takes effect at once). Disabling never loses events; they remain in Zabbix and can be re-notified by hand if needed.

## 7. Rollback

```bash
$H --env lab action rollback --backup state/backups/hardware-action-lab-<stamp>.json   # id- and nonce-verified; deletes the action this tool created, or restores the prior definition
$H --env lab template rollback --definition <id>                                         # exact recorded id only; restores the immutable pre-change export, or deletes the tool-created template; refuses linked / drifted / foreign templates
```
Tag changes made on the simulator triggers are reverted with the saved `RESTORE plan` (operator-applied). Code rollback: `release/rollback.sh`. Rollback never touches an object this deployment cannot prove it owns.

## 8. Not tested / out of scope

Real Telegram delivery (**NOT TESTED**), Production e-mail, escalation policies, acknowledgement flow, message rendering in Telegram clients (HTML mode / long-event-name wrapping).

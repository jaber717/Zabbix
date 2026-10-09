# Separate notification action: NETOPS-HW Hardware Health

**Status: DESIGN + guarded tooling. DISABLED. Problem/Recovery delivery is NOT TESTED. Hardware notifications are NOT operational.**

## Why a separate action

The Interface Alerting v1.0.2 action (`NETOPS-IaC Interface Alerts`) fires on one thing: event tag `netops_alert` present. Hardware events must neither reach it nor depend on it, and the interface action must never fire for hardware. Today's stock hardware triggers carry only broad `scope` / `component` tags (shared with non-hardware triggers; two unrelated Linux `component=system` notices were found in the 30-day event history), so no existing tag can safely identify a hardware event.

## Tag contract (what a hardware trigger must carry)

| Tag | Value | Required | Purpose |
|---|---|---|---|
| `netops_hardware` | `1` | **yes** | the only routing key; positive allowlist |
| `hardware_component` | `fan` \| `power` \| `temperature` \| `redundancy` \| `ha` \| `sensor_stale` | **yes** | what failed; the audit checks it equals the policy category (`hw_redundancy` -> `redundancy`) |
| `hardware_vendor`, `hardware_model`, `hardware_site`, `hardware_slot` | free text | recommended | payload content (macros `{EVENT.TAGS.<name>}`) |
| `netops_alert` | - | **forbidden** | belongs to Interface Alerting; a trigger with both is reported `TRIGGER_CROSS_TAGGED` |

`ha` (cluster / HA member state) and `redundancy` (fan / PSU redundancy) are separate components with separate triggers; neither stands in for the other. `sensor_stale` is for monitoring-quality triggers (stale sensor, SNMP unavailable) - a missing SNMP answer is never reported as a fan or PSU failure.

## Action definition (created by `hardware_audit.py --env lab action apply`)

| Field | Value |
|---|---|
| name | `NETOPS-HW Hardware Health` (prefix `NETOPS-HW ` = ownership marker; fixed) |
| event source | trigger (0) |
| status | **disabled (1)** |
| evaluation | AND (`evaltype` 1) |
| condition A | type 26 *event tag value*, operator equals, tag `netops_hardware`, value `1` |
| condition B | type 25 *event tag*, operator does-not-equal, tag `netops_alert` |
| Problem operation | send message, existing media type (name from `config/notifications.<env>.yaml`), existing user group(s); subject/message carry host, vendor/model, site, slot, component, severity, date/time, event ID, status |
| Recovery operation | same recipients, `[HARDWARE RESOLVED]`, recovery time and duration |

Never used for routing: host group, host name, trigger-name text, `scope`, `class`, `component`, `target` tags.

The media type and user groups are operator-owned and must already exist; the tool never creates or changes them. Production is e-mail, LAB may use the existing Telegram media type; the two use different configuration files and credentials. **Production management is refused in this release.**

## Safety mechanisms

* Read-only API client for audit/discovery; the action tool opens a write-capable client only for `apply|rollback`, and that client can write nothing except `action.create|update|delete`.
* `plan` is a dry run: CREATE / UPDATE with the differing fields, conflicts (missing media type or user group, wrong environment), and the crossover model.
* Ownership: the fixed `NETOPS-HW ` name; the Interface Alerting action is read (to check its filter) and never written. A test asserts its object is byte-identical after apply.
* Idempotent: a second `apply` reports "no changes" and makes no write. Drift (changed filter, operations, status) shows as `UPDATE [fields]` and is repaired.
* Backup before every write: `state/backups/hardware-action-<env>-<time>.json` (mode 0600; ids and definitions only, no credentials; the `state/` directory is Git-ignored). `rollback --backup F` deletes an action this tool created or restores the previous definition.
* Readback: after a write the plan is recomputed; any difference is an error that names the backup.
* **Enable gate:** `--enable` is honoured only when `config/action-validation.yaml` records independently verified Problem delivery, Recovery delivery and interface exclusion, each with an evidence reference, and `validated_by`. The shipped file is all `false`. A live action found enabled without that evidence is reported and set back to disabled by the next `apply`.

## Offline proof vs live proof

`hwh/action.py::event_matches` models the two condition types as documented for Zabbix 7.0. Seven sample events (hardware fan/PSU, interface link-down/utilization, a stock `scope`-only hardware trigger, a Linux `component=system` notice, a trigger carrying both families) are checked against both actions, and the live Interface Alerting action filters are read and checked as well; tests fail if any event could reach the wrong action. That is a model of Zabbix, not Zabbix. The live acceptance below is the authority.

## Live acceptance for the action (HW-N1 .. HW-N6, independent tester, LAB)

| ID | Test | Pass |
|---|---|---|
| HW-N1 | `action plan`, `action apply` | disabled action created; Interface Alerting action unchanged |
| HW-N2 | `action apply` again; hand-edit the filter; `plan`; `apply` | idempotent; drift detected and repaired |
| HW-N3 | `action rollback --backup` (create and update cases) | state restored; foreign actions untouched |
| HW-N4 | with the action enabled by the tester for the test only: raise a **real or safely simulated** hardware Problem and its Recovery on a trigger tagged per the contract | one Problem and one Recovery message with all payload fields; no Interface Alerting message |
| HW-N5 | raise an interface event (`netops_alert`) | delivered by Interface Alerting only; nothing from this action |
| HW-N6 | raise events from a stock trigger without the dedicated tags and a trigger tagged with both | neither notifies through this action |

Record results in `config/action-validation.yaml` (not before they exist).

## Getting the dedicated tags onto triggers (open design decision - NOT implemented)

Inherited template triggers cannot be re-tagged on the host, and editing stock vendor templates is a maintenance burden. Two candidate mechanisms, to be chosen after real devices exist and each trigger has been vetted against that vendor's real status semantics:

* **A. A NETOPS Hardware template** (imported with `configuration.import`, as the alerting project does for interfaces) holding vetted triggers on the stock items, carrying the contract tags. Hosts link it in addition to the vendor template. Recommended: reversible (unlink), diff-able, one place to review.
* **B. Cloning stock triggers** per template with tags added. Simpler per trigger, but forks vendor content.

Neither is built: building tagged triggers before a real device proves what the items return would encode guesses. The audit reports `TRIGGER_NOT_ROUTABLE` until the tags exist.

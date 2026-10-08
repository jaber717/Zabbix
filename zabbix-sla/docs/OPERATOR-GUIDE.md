# Operator guide

Audience: the NOC engineer who maintains the service model and reads the monthly SLA numbers. You edit YAML and run `./sla.sh`; there is no GUI to maintain.

> Status: LAB only. Nothing here is approved for Production until the independent live acceptance (ACCEPTANCE-MATRIX.md) has passed.

## 1. Setup (once per machine)

```bash
git clone <repo> && cd <repo>/zabbix-sla         # deployed straight from GitHub on the VM
cp config/.env.example .env && chmod 600 .env     # then put the LAB URL and an SLA-platform token in it - never commit .env
python3 -c 'import yaml'                           # PyYAML must import; Python 3.9+
```

One API token per environment, scoped to the SLA platform (read `host/item/trigger/service/sla/dashboard/usermacro`; write `service/sla/item/trigger/dashboard`). Do not reuse the alerting token.

## 2. Daily commands

| Command | What it does | Changes Zabbix? |
|---|---|---|
| `./sla.sh --env lab check` | Validates `inventory/lab.yaml` and shows what it compiles to. Needs no network. | no |
| `./sla.sh --env lab plan` | Compares the inventory with Zabbix: `CREATE`, `UPDATE [fields]`, `ORPHAN`, `CONFLICT`. | no |
| `./sla.sh --env lab apply` | Backs up, writes in order, then re-reads Zabbix and verifies. | **yes** |
| `./sla.sh --env lab verify` | Drift check. Exit 2 = Zabbix no longer matches the inventory. | no |
| `./sla.sh --env lab quality` | Does every link have a working "down" signal? | no |
| `./sla.sh --env lab report --month 2026-10 --out r.json [--suite-doc d.json]` | Monthly SLI / error budget with qualification. | no |
| `./sla.sh --env lab simulate --down int-core--mobily` | What-if on the compiled tree (offline). `--alert link:util_rx`, `--probe-down id`, `--probe-stale id`. | no |
| `./sla.sh --env lab dashboards plan\|apply` | Executive and NOC dashboards from `dashboards/*.yaml`. | apply: yes |
| `./sla.sh --env lab rollback --backup state/backups/<file>.json` | Restores the state recorded in a backup. | **yes** |

Add `--prune` to `plan`/`apply` only when you want objects that were removed from the inventory to be deleted; otherwise they are listed as `ORPHAN` and left.

## 3. Reading the output

* `CONFLICT ... never adopted` - someone created an object with a NETOPS-SLA name by hand. Rename or delete it in Zabbix; the tool will not take it over.
* `warn ... left in place` - an object this tool owns is no longer in the inventory.
* `READBACK VERIFICATION FAILED` - the write succeeded but Zabbix does not hold what the inventory says. Do not continue; use the printed `rollback --backup` command and report it.
* `REFUSED: IDENTITY MISMATCH` - the server you pointed at says it is a different environment. Stop and check the URL.
* Status words in reports: **COMPLIANT** (met SLO with sufficient data), **BREACHED**, **INSUFFICIENT_DATA** (the monitoring behind the figure cannot support a statement; it is shown as N/A, never as 100 %). Read the *Notes / caveats* column.

## 4. Common edits (all in `inventory/<env>.yaml`)

* **Add a link:** add under `components:`; add it to the `components:` list of each `paths:` entry that uses it. `link_id` must be the value of the existing `link_id` event tag.
* **Add a redundant route:** add a `paths:` entry and list it in the `members:` of the `connectivity:` it protects. Do **not** add a fallback "through transit" unless you also mark it `{ref: ..., fallback_via_transit: true, verified: true, evidence: <where the proof is>}`; otherwise it is ignored on purpose.
* **Change an SLO:** edit `slo:` and set `approved: true` only with the approval reference in `source:`. SLOs with `approved: false` can be applied in LAB and are refused in Production.
* **Planned maintenance (excluded from the SLI):**

  ```yaml
  planned_downtime:
    - {id: pd-2026-11-a, slas: [connectivity-standard], start: '2026-11-14T01:00:00+03:00', end: '2026-11-14T03:00:00+03:00',
       reason: INT-CORE software upgrade, ticket: CHG-1234, approver: noc-lead}
  ```

  Ticket, approver and reason are mandatory; the window may not exceed `settings.planned_downtime_cap_hours` (default 8); it must be entered **before or during** the month it belongs to - once the month is closed the tool refuses to add, change or remove it. List it in the monthly report (done automatically).
* **Activate a probe:** only after the runner, ≥ 2 independent destinations and a routing proof are confirmed. Set `status: active`, `runner:` to the Zabbix host name, real `address:` values, and `verification:` to `pinned_destination`, `source_pbr` or `traceroute`. `verification: none` is reachability-only and cannot back a verified service.

## 5. What the numbers mean

* **Inferred (T2)** - built from link up/down; it can over-state availability when a link is up but traffic is not flowing. Always labelled "inferred from link state".
* **Verified end to end (T3)** - additionally requires an active probe with routing proof and fresh data. Only this may be called verified.
* **Utilization, errors, discards, flapping** never count as downtime. They stay in the NETOPS alerts.
* **Provider SLA claims** are not in these reports. Our figure is what we measured on our side of the link.
* A **stale probe** is a data-quality problem, not downtime: it appears under "Monitoring-data quality" and turns the affected verified figure into INSUFFICIENT_DATA.

## 6. Something looks wrong

1. `./sla.sh --env lab verify` - drift?  → `apply` repairs it (the diff names the field).
2. `./sla.sh --env lab quality` - a link without a signal makes its services INSUFFICIENT_DATA; fix the monitoring (NETOPS alerting) rather than the SLA.
3. A service is red in Monitoring → Services: open it, look at **Problem tags**; the matching problems are the ones carrying those tags.
4. Roll back the last change: `ls state/backups/` and `./sla.sh --env lab rollback --backup <the file taken before the change>`.

## 7. What not to do

Do not edit NETOPS-SLA services, SLAs or the `[NETOPS-SLA]` triggers in the Zabbix GUI (the next `verify` reports drift and `apply` reverts it); do not put tokens in the repository; do not point `--env production` at anything until the production runbook has been followed.

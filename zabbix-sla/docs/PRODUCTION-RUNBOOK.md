# Production deployment runbook

**Do not start this runbook until:** (1) the independent live acceptance A-01..A-25 is complete with no blocking FAIL (ACCEPTANCE-MATRIX.md), (2) the production inventory has been reviewed and the change is approved in writing, (3) a maintenance/communication window is agreed. Nothing in this repository schedules, enables or applies anything on Production; every step below is a manual, attended action.

## 0. Preconditions checklist (all must be "yes")

| # | Check | Evidence |
|---|---|---|
| 1 | Acceptance results file shows PASS (or accepted PASS WITH LIMITATIONS) for A-01, A-04, A-09, A-11, A-15, A-19 | `docs/ACCEPTANCE-RESULTS.md` |
| 2 | Production Zabbix reports API 7.0.x and `{$NETOPS.ENVIRONMENT}` = `production` (created by `zabbix-alerting --init-identity` during its own approved rollout) | `apiinfo.version`, `usermacro.get` |
| 3 | `zabbix-alerting` v1.0.1 is already applied on Production and its `plan` shows no drift (the link problems the services depend on must exist) | alerting `apply.sh --env production --dry-run` |
| 4 | Production API token exists, scoped as in OPERATOR-GUIDE §1, stored only in the production host's `.env` (mode 600) | role listing |
| 5 | `config/environments/production.yaml`: `url_regex` set to the real production URL (the shipped placeholder matches nothing) | file review |
| 6 | `inventory/production.yaml` written from the LAB inventory with production `link_id`s, real SLOs with `approved: true` and an approval reference in `source:` | PR review |
| 7 | `tag_semantics: and` recorded from A-01 (same minor version on Production, or A-01 repeated there in a window) | evidence |
| 8 | Rollback owner and a second person identified | change record |

## 1. Prepare (read-only, any time)

```bash
cd zabbix-sla && git fetch && git checkout <approved tag>      # deploy a tag, never a moving branch
./sla.sh --env production check                                # offline: inventory valid, environment declared 'production'
./sla.sh --env production plan                                 # read-only: shows exactly what would be created
./sla.sh --env production quality                              # every link has a working down signal?
```

Review `plan` line by line with the second person. Expected on a first rollout: only `CREATE`. Any `CONFLICT` or `UPDATE` on an object you did not expect stops the rollout.

## 2. Apply (attended, inside the window)

```bash
./sla.sh --env production --confirm production apply
```

The banner must read `ENVIRONMENT : PRODUCTION`, the production URL, `IDENTITY : ok`. The run takes a backup, writes, then verifies by reading back. Required outcome: `readback verification: PASS`. Record the backup path.

## 3. Verify

```bash
./sla.sh --env production plan          # expect: no changes
./sla.sh --env production verify        # expect: exit 0
```

In Zabbix: Monitoring → Services → "NETOPS-SLA: Service assurance": every service OK unless a real outage exists; open one link service and confirm its problem tags. Confirm **no notification** was produced by the new objects (they carry no `netops_alert` tag) and the alerting plan still shows no drift.

## 4. Roll back (if anything is unexpected)

```bash
./sla.sh --env production --confirm production rollback --backup state/backups/production-<stamp>.json
./sla.sh --env production verify        # against the previous inventory revision: exit 0
```

Rollback removes what the apply created and restores what it changed; it never touches objects it does not own. It is itself backed up first. Ids of recreated objects change.

## 5. After go-live

* First report: run `report --month <closed month>` only after at least one full month of data; until then reports say `INSUFFICIENT_DATA` / month-to-date by design.
* Dashboards (`dashboards apply`) and probes follow their own gates (A-20, A-16); they are separate changes with separate approvals.
* Reporting-suite scheduling (daily/weekly/monthly PDF/XLSX/e-mail) is configured in that project, not here, and needs its own approval.
* Planned maintenance: record every window in `planned_downtime` *before* the month ends, with ticket and approver.
* Review at 30 days: drift runs (`verify`), `quality`, error-budget burn, any `INSUFFICIENT_DATA` services and why.

## 6. What is deliberately NOT part of this rollout

No scheduling or cron/timer of any kind; no e-mail; no change to the Zabbix server configuration or to `zabbix-alerting`; no probe activation; no database access; no automatic apply.

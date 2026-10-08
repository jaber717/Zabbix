# Acceptance matrix

Two columns matter: **Offline** = what the automated suite already proves against the Zabbix API *model* (`tests/`), and **Live** = what only a real Zabbix can prove. The platform is **not production-ready until every Live item below has been executed by the independent tester (Codex) and its evidence is in `evidence/`**. Offline passing is necessary, not sufficient: the API model was written from documentation.

Legend: RO = read-only, LAB-W = writes to the LAB Zabbix only, INJ = needs a controlled LAB failure (interface shutdown etc.), never production.

| ID | What is proven | Procedure (LAB) | Pass criterion | Offline coverage | Evidence file |
|---|---|---|---|---|---|
| A-01 | Several service problem tags combine with **AND** (gate for every link service) | `python3 scripts/accept_tag_semantics.py --env lab --host <host> --item-key <key>` (LAB-W) | `RESULT: AND`, cleanup `ok` | mock honours AND/OR; script logic tested | `tag-semantics-lab.json` |
| A-02 | Real shapes of `service.get`, `sla.get`, `sla.getsli`, `dashboard.get` match what the planner reads | After first apply: `python3 scripts/accept_api_shapes.py --env lab` (RO) | all checks PASS | model mirrors the same checks | `api-shapes-lab.json` |
| A-03 | Least privilege: the read token cannot write; the write token can only do service/sla/item/trigger/dashboard | Try `apply` with a read-only role token; try with the write token | read token → refused by Zabbix, write token works; list the role | `ReadOnlyViolation` guard tested | role listing |
| A-04 | Environment isolation: LAB inventory/commands cannot reach production | (a) `--env production` with the LAB URL; (b) LAB URL in the production variable; (c) macro set to `production` on LAB then `--env lab` (restore after) | all refused before any write; `apply` on production without `--confirm production` refused before contact | `TestEnvironmentIsolation` | transcript |
| A-05 | Provision from empty LAB | `./sla.sh --env lab check; plan; apply` | apply ends `readback verification: PASS`; 32 services, 2 SLAs (shipped inventory); Monitoring → Services shows tree under "NETOPS-SLA: Service assurance" | `test_full_apply_verify_rollback_with_proven_semantics` | transcript + screenshot |
| A-06 | Idempotence | `plan` and `apply` again | "no changes"; no new backup | `test_second_apply_is_a_noop` | transcript |
| A-07 | Semantic drift detection and repair | By hand in the GUI change: a service algorithm, a problem tag, remove a child link, an SLO; then `verify` (exit 2, names the field), `apply`, `verify` (exit 0). Also delete + recreate a service by hand and confirm ids alone are not drift | each change named; repaired | `TestDrift` | transcript |
| A-08 | Ownership: foreign objects untouched | Pre-create an unmanaged service with a NETOPS-SLA name; add a manual child to the root | conflict reported and nothing written; manual child preserved | `TestOwnership` | transcript |
| A-09 | **Single ISP failure does not mark the business service down** (INJ) | Shut INT-CORE↔MOBILY; wait 2 min; read Monitoring → Services; restore | `lnk.int-core--mobily` and `path.siteA.intl.direct` PROBLEM; `conn.siteA.international`, `svc.siteA.internet`, `root` OK. Repeat for STC, `mobily--site-a`, `stc--site-b` | `LabScenarios` (model) | per-failure screenshots + `service.get` dump |
| A-10 | Both ISPs down marks both sites' internet down (INJ) | Shut INT-CORE↔MOBILY and INT-CORE↔STC | both `svc.*.internet` PROBLEM; SAIX services still OK | model | dump |
| A-11 | **Utilization is not downtime** | Raise a `util_rx`/`util_tx` problem on a link (lower the threshold macro, or generate traffic) while the link is up | the NETOPS problem appears; **no** service changes status; SLA downtime unchanged | model + hazard test | dump + `sla.getsli` before/after |
| A-12 | National redundancy and **transit fallback truth** (INJ) | Fail `saix-a--site-a`; then also `saix-b--site-b`. During the second failure record from SITE-A/B whether national prefixes still reach SAIX-CORE through the transit | one leg: national OK via inter-edge. Both legs: services PROBLEM; **record** whether traffic fell back (decides E-06) | model | traceroute/route evidence |
| A-13 | Inter-site (INJ) | Fail `site-a--site-b` | `svc.inter-site` PROBLEM (only the direct path is modelled); record whether traffic reroutes via transit | model | dump + routes |
| A-14 | Partial-coverage limitation is real | Fail SAIX-CORE's far end of `saix-core--saix-a` without dropping SITE-side link state | T1 does not see it (documented limitation) - confirm and keep the report caveat | caveat tests | note |
| A-15 | Monitoring-quality validation | Disable the `link_down` trigger(s) of one link; run `./sla.sh --env lab quality` and `report` | link `DISABLED/MISSING`; services using it `blind` → `INSUFFICIENT_DATA`, not compliant; re-enable → OK | `TestReport` blind/partial tests | transcript |
| A-16 | Active Assurance probe (after E-04..E-07) | Activate one probe in the LAB inventory; `apply`; fail destinations one by one; stop the runner/disable an item | items + calculated item + 2 triggers created; K-1 destinations down → no problem, K → `sla_probe`; stale → `sla_probe_stale` and `quality.*` PROBLEM but the business service stays OK; T3 figure → `INSUFFICIENT_DATA` | probe generation + report tests | dump |
| A-17 | Monthly SLI/error budget against Zabbix's own SLA report | After injected downtime: `./sla.sh --env lab report --month YYYY-MM --out r.json` | SLI/uptime/downtime equal the GUI "SLA report" within 1 s; error budget arithmetic matches; `INSUFFICIENT_DATA` where expected | `TestSloMath`, `TestReport` | `r.json` + GUI screenshot |
| A-18 | Planned downtime policy | Add a ticketed window inside the current month; apply; confirm the SLA shows it as excluded and the report lists it. Then try a window in a closed month and an over-cap window | accepted/applied; closed-month and over-cap refused | `TestHistoryImmutable`, validator tests | transcript |
| A-19 | Rollback incl. partial failure | (a) apply a change set, `rollback`; (b) make `apply` fail midway (e.g. token role without `sla.create`) then `rollback` with the printed backup | state equals the pre-apply state (`verify` against the old inventory = exit 0); foreign objects intact | `TestRollback` | transcript |
| A-20 | Dashboards (after E-10) | Build the reference dashboard by hand; `scripts/accept_widget_fields.py`; `dashboards plan`; `dashboards apply`; edit a widget; `plan` shows UPDATE | widgets render real data; drift repaired | `TestDashboards`, `TestWidgetEvidence` | screenshots + `widget-field-types.json` |
| A-21 | Reporting suite renders the SLA document | After the adapter (INTEGRATION-REPORTING.md): render `--suite-doc` output to PDF/XLSX/JSON | no `N/A` replaced by numbers; INSUFFICIENT rows visible; planned downtime listed | `TestBridge` (shape) | rendered files |
| A-22 | No secrets in Git or state | `git grep -nIi 'token\|password'` on the branch; inspect `state/` | no credential values; `.env` ignored | backup test | grep output |
| A-23 | No direct database change; supported API only | Compare Zabbix audit log (`auditlog.get`) for the test window with the journal | only API users' service/sla/item/trigger/dashboard actions | - | audit extract |
| A-24 | Coexistence with `zabbix-alerting` v1.0.1 | Run the alerting `apply.sh --env lab --dry-run` before and after the SLA apply; trigger a link_down | alerting plan unchanged; Telegram notification content/count unchanged; no notification for SLA/probe objects | SLA objects carry no `netops_alert` tag | both transcripts |
| A-25 | Runtime and scale | Time `apply` and `plan` for the shipped inventory | seconds, not minutes; API call count recorded | - | timing |

## Result template (one row per item, in `docs/ACCEPTANCE-RESULTS.md`)

```text
A-xx | PASS / FAIL / PASS WITH LIMITATIONS | date | tester | evidence file | notes
```

The final statement is made only after A-01..A-25 are filled in. Any FAIL in A-01, A-04, A-09, A-11, A-15 or A-19 blocks production regardless of the rest.

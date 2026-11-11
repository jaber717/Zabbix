# Remediation of the v1.1.0 independent review (98bd925 → branch `claude/discovery-onboarding-v1.1-remediation`)

Review decision on `98bd925`: **CONDITIONAL NO-GO**. Every claim was reproduced on `98bd925` before any change. All fixes
are offline-tested only; **nothing was run against a real Zabbix, LAB or Production.** Nothing was merged, tagged or released.
Tag `v1.0.2` is unchanged.

## 1. Findings

### Confirmed defects (reproduced on 98bd925, fixed, regression-tested)

| # | Sev | Defect (reproduction on 98bd925) | Fix | Regression test(s) |
|---|---|---|---|---|
| R1 | P0 | A project-managed port that is neither approved nor a candidate was **PROTECTED without any utilization alert** | utilization proof required for every protected class | `test_managed_port_without_utilization_alert` |
| R2 | P0 | **Any** enabled trigger on the status item counted as a link alert (e.g. `nodata(...)=1`, `=7`) | expression must compare the oper-status item with `=2` / `<>1`; utilization must compare a traffic item with `>`; otherwise "unproven" | `test_trigger_on_status_item_must_test_link_down` |
| R3 | P0 | Recovery operation existence only; **recovery recipients never checked** | Problem (immediate step) and Recovery recipients proven separately; type 11 inherits problem recipients | `test_recovery_recipients_verified_separately`, `test_recovery_media_type_disabled` |
| R4 | P0 | User media **active period ignored** | media must be active `1-7,00:00-24:00`; restricted periods are named | `test_media_active_period_restricted` |
| R5 | P0 | Host-group conditions ignored **nested groups** → `not equals parent` evaluated True (overclaim) | nested matching by group path; unknown group → unknown | `test_nested_host_group_negative_condition` |
| R6 | P0 | **Template-level tags** not read → negative tag conditions evaluated True (overclaim) | template ancestry with tags/macros read; unreadable templates → negative tag conditions unknown | `test_template_level_tag_negative_condition`, `test_template_condition_respects_inheritance` |
| R6b | P0 | Trigger gating macros (`{$IFCONTROL}`, `{$NETOPS.*}`) only checked at host level | full resolution host → template ancestry → global (context, then plain); unresolvable gate → fail closed; closed gate → NOT COVERED | `test_unresolvable_gate_macro_fails_closed`, `test_gate_closed_at_template_level` |
| R6c | P0 | Delayed-only operations, hosts in maintenance counted | immediate operation required; maintenance → PARTIAL | `test_only_delayed_problem_operation`, `test_host_in_maintenance` |
| R6d | P0 | No distinction between configuration and delivery | `CONFIG VERIFIED (DELIVERY NOT TESTED)` vs `PROTECTED (DELIVERY TESTED)` (Zabbix alert history: a **sent** problem **and** recovery message from that action for that trigger within 90 days) | `test_delivery_tested_requires_sent_problem_and_recovery` |
| R7 | P0 | Re-pairing A↔B → A↔C left B paired to A and **all three ports shared one link_id** | `set_pair` releases old partners on both sides; link_id kept only for an unchanged relationship, otherwise regenerated; stale shared ids dropped; ids used by >2 entries never written | `test_repair_releases_old_partner_and_never_reuses_link_id`, `test_single_ended_releases_partner`, `test_endpoint_removal_drops_link_id_and_blocks_until_resolved` |
| R7b | P0 | Inconsistent existing inventories (id on 3 entries, same-host ids, non-reciprocal decisions, NetBox re-cabling) not detected | one-to-one reciprocal resolution (decision > NetBox cable > inventory); every disagreement is a deploy-blocking ISSUE; `w` refuses to rewrite a conflicting id until each end is decided | `test_inconsistent_existing_inventory_is_blocked`, `test_non_reciprocal_decisions_are_blocked`, `test_netbox_topology_change_is_a_blocker`, `test_link_id_checker`; preserved: `test_unchanged_relationship_keeps_historical_link_id` |
| R7c | P0 | Unpaired P2P was only a warning | blocker until paired or explicitly confirmed single-ended (`p N -`) | `test_unmatched_p2p_endpoint_blocks_until_confirmed_single_ended` |
| R8 | P0 | Gate passed although **decisions changed after the last write** (deploy would ship a stale inventory) | decisions hash bound at write; both inventories **regenerated and compared** during verify; approval token binds code commit + decisions + both files + both live plans; `--deploy` requires that exact token | `test_decisions_changed_after_write_block_deploy`, `test_inventory_must_equal_regenerated_inventory`, `test_approval_token_binds_the_reviewed_state`, `test_missing_identity_evidence_blocks` |
| R9 | P0 | OSPF/BGP enabled while **UNVERIFIED** passed as a warning | blocker until per-device evidence (`ev`), an expected list (`ex`), and Network Health LAB acceptance for production | `test_unverified_health_blocks_until_evidence_expected_and_acceptance`, `test_production_health_apply_blocked_without_lab_acceptance` |
| R10 | P1 | NetBox pagination followed `next` to **any host** (token sent; original loops forever) | `next` must stay on the configured scheme, host, port and `/api/` path | `test_netbox_pagination_stays_on_origin_and_api_path` |
| R11 | P1 | HTTP redirects forwarded credentials: `Authorization: Bearer <Zabbix token>` and `Token <NetBox token>` reached a second origin. **The Zabbix part is also in the accepted v1.0.2 code** (`netalert/zbx.py`) | both clients refuse every redirect (fail closed, token never re-sent) | `test_zabbix_transport_refuses_redirects`, `test_netbox_refuses_redirects` |
| R12 | P1 | `p N -` (unpair) **crashed the review session** (`NoneType.id`, uncaught) | `p N -` = confirmed single-ended, releases the partner | `test_single_ended_releases_partner` |
| R13 | P1 | Interface Alerting and Network Health applied sequentially without a joint preflight (shown: health import failed after interfaces were applied) | read-only dry-run of **both** components before the first write; any failure blocks everything; a partial apply is reported with recovery steps (no atomic-rollback claim) | `test_preflight_runs_before_the_first_write_and_partial_apply_is_reported` |
| R14 | P1 | Production deploy did not prove which code ran | production requires a clean checkout whose HEAD equals `deploy_pin` (validated commit/tag) | `test_production_code_must_be_clean_and_pinned` |
| R15 | P1 | OSPF/BGP: router SNMP-blind → neighbor triggers simply stop evaluating (**silent green**); lost neighbors' items deleted after 7 days → problem closed **without recovery**; neighbors that never reached Full undetected | stored scalar + `nodata()` "monitoring data LOST" trigger; LLD `DELETE_NEVER`; expected-neighbor/peer check | `test_templates_detect_blindness_and_never_delete_lost_neighbors`, `test_expected_lists_validated_and_written_as_macro` |

Already safe on 98bd925 (kept as guard tests): time-period action conditions evaluated as *unknown* (`test_time_period_condition_fails_closed` passes on both).

### Suspected risks (not reproducible offline — must be closed in LAB)

| Risk | Why it is only suspected | Closure |
|---|---|---|
| API parameter compatibility: `host.get selectHostGroups`, `usergroup.get selectHostGroupRights`, `user.get selectMedias(period)/selectUsrgrps`, `trigger.get itemids/expandExpression`, `template.get selectParentTemplates/selectTags/selectMacros`, `event.get select_alerts`, `item.get tags/search` | written from Zabbix 7.0 documentation; the mock answers what we told it to | `scripts/capture-api-fixtures.py` in LAB → `tests/test_recorded_fixtures.py` (currently **NOT RUN**) |
| Exact expanded expression text of the stock "Link down"/"High bandwidth" triggers | regex matches the documented shape | replay of recorded triggers; if not matched the port shows PARTIAL "unproven" (fails closed, never overclaims) |
| Network Health template import (value maps, walk items, `SNMP_WALK_TO_JSON` in non-LLD items, JavaScript, `length()`) | never imported anywhere; the offline model rejects `valuemaps` | LAB import (docs/NETWORK-HEALTH.md §8) |
| Huawei VRP exposes only one OSPF process via OSPF-MIB (`ospf mib-binding`) | vendor behaviour, not testable offline | LAB `snmpwalk` per device; expected-neighbor list exposes missing neighbors |
| Recovery delivery for `notify all involved` (type 11) | assumed = problem recipients | LAB fault test with e-mail |

### Accepted limitations (by design, documented)

Coverage under-reports rather than over-claims: time-period conditions, regex macro contexts, unreadable users/templates/
history, unknown expression shapes → never protected. DELIVERY TESTED requires a historical sent problem+recovery pair
(90 days); a new deployment is at most CONFIG VERIFIED until a fault test. OSPFv2/IPv4 BGP only, default instance/VRF;
expected lists are entered once per device (`ex N ospf seen` adopts what Zabbix sees up after the first deploy).
No atomic multi-component rollback.

## 2. Changed files (minimal; architecture unchanged)

`netalert/coverage.py` (rewritten classification), `netalert/discovery.py` (expressions, template ancestry, global macros,
host groups, media periods, maintenance, delivery history), `netalert/onboarding.py` (pairing, link_id integrity, gate,
health evidence/expected), `netalert/onboard_cli.py` (preflight, approval token, code pin, partial-apply report),
`netalert/review.py` (`p N -`, `ev`, `ex`), `netalert/netbox.py` + `netalert/zbx.py` (no redirects, origin-bound
pagination), `netalert/apirecord.py` + `scripts/capture-api-fixtures.py` (real-API fixtures),
`nethealth/{templates,config,planner,cli}.py` (blind/expected/DELETE_NEVER, production block).
Interface Alerting trigger logic, template, schema, planner and applier: **unchanged** (only `zbx.py` transport hardened).

## 3. OSPF / BGP technical assessment (Network Health, after remediation)

| # | Question | Answer (template logic) | Proven? |
|---|---|---|---|
| 1 | Established neighbor drops FULL → EXSTART/DOWN | `max(state,2m)<8 and count(state,24h,"eq",8)>0` fires after 2 min not Full; recovery on Full. A bounce shorter than 2 min is not alerted (by design; `ospfNbrEvents` flap detection not implemented) | logic only — LAB fault test required |
| 2 | Neighbor disappears from the SNMP table | `SNMP_WALK_VALUE` miss → state 0 → fires; item kept forever (`DELETE_NEVER`) so the problem cannot close silently; expected-list check also fires | logic only |
| 3 | Router unreachable / SNMP silent | walk fails → per-neighbor items get no values; **new** `nodata(nhealth.ospf.alive,5m)` "monitoring data LOST" fires (plus Device Unreachable / SNMP Stale if enabled). Open neighbor problems stay open | logic only |
| 4 | Neighbor never Full in the lookback | per-neighbor trigger cannot fire (intentional: avoids DROTHER 2-Way noise); **expected list** fires for any expected router-id not Full. Without an expected list the gate blocks production | logic + gate tested offline |
| 5 | Identify expected neighbors / missing coverage | `{$NHEALTH.OSPF.EXPECTED}` from the inventory (`ex N ospf ...` / `seen`); coverage report flags devices without blind or expected alerts | gate/report tested offline |
| 6 | Huawei: all neighbors via the selected context/process? | **No guarantee.** VRP's OSPF-MIB shows one bound process (`ospf mib-binding`); multiple areas of that process are in one table. Other processes / VPN instances are invisible → appear as *missing expected neighbors* (detected, not silently green) | LAB `snmpwalk` per router |
| 7 | Unsupported MIB vs healthy adjacency | unsupported MIB → `alive` scalar unsupported/no data → "monitoring data LOST"; the item error text tells which. Never shown as healthy | logic only |
| 8 | Problem/Recovery e-mail routing | events carry `netops_alert` (`ospf_neighbor`, `ospf_blind`, `ospf_expected`, `bgp_*`) → existing NETOPS-IaC e-mail action; coverage report proves the path per device | offline only; **no e-mail ever sent** |

Firewall adjacencies (FortiGate/Palo Alto) are monitored **from the Huawei router's neighbor table**. Monitoring OSPF on the
firewalls themselves is not claimed. No router or firewall configuration is part of this project.

**Network Health remains blocked from Production** (`apply-health.sh` and `--deploy` refuse without
`network_health_lab_acceptance` in `config/environments/production.yaml`). Required LAB acceptance: docs/NETWORK-HEALTH.md §8.

## 4. Updated safe deployment workflow

```bash
./onboard.sh --env production                    # review; w writes inventories + binds decisions
git add config && git commit -m "approved inventory"
./onboard.sh --env production --verify           # gate + read-only preflight of both components -> APPROVAL TOKEN
./onboard.sh --env production --deploy --confirm production --approve <TOKEN>
./onboard.sh --env production --report           # expect CONFIG VERIFIED; DELIVERY TESTED only after a real fault test
```
The token changes if anything changed after review: code commit, decisions, either inventory, or the live plan of either
component. Production additionally requires a clean checkout at `deploy_pin`. Partial apply: reported; re-run the same
verify/deploy, or roll back from git (docs/ONBOARDING.md §7). Installation: docs/ONBOARDING.md §2 (pinned commit,
FortiProxy CA, `no_proxy` for Zabbix/NetBox, retries for proxy 504s; TLS verification is never disabled).

## 5. Regression results

| Run | Result |
|---|---|
| Full suite, Python 3.13.17 | **265 run: 264 pass, 1 skipped = NOT RUN** (real-Zabbix recordings absent) |
| Full suite, CPython 3.9.25 + PyYAML 6.0.3 (RHEL 9 runtime) | 265 run: 264 pass, 1 NOT RUN |
| `-W error::ResourceWarning` | pass |
| `scripts/release-gate.sh` (syntax 81 Py / 36 sh, tests, secret scan incl. history, ShellCheck 0.11) | **PASS** |
| `tests/test_remediation.py` (35) against **98bd925** (shim: alias `CONFIG=PROT`, `run(code_check=)` accepted — no behaviour change) | **34 fail** (27 assertion failures, 7 errors: missing safety APIs, and the R12 crash), **1 pass** (time-period guard, already safe) |
| Real Zabbix API compatibility | **NOT RUN** |
| Network Health template import, LLD, triggers, fault/recovery | **NOT RUN** |
| E-mail Problem/Recovery delivery | **NOT RUN** |

## 6. GO / NO-GO

| Decision | Verdict |
|---|---|
| Merge / tag v1.1.0 | **NO-GO** until LAB: recorded-fixture replay passes, onboarding regenerates the accepted 18-port LAB inventory with `No changes required.`, and one deployed port reaches DELIVERY TESTED through a real e-mail fault test |
| Production Interface Alerting via onboarding | **NO-GO** until the above, plus the read-only production `--report` reviewed and the deploy pinned to the validated commit |
| Production Network Health | **NO-GO (blocked in code)** until independent LAB acceptance per docs/NETWORK-HEALTH.md §8 |
| Remediated code (offline) | every confirmed P0/P1 defect fixed with a regression test that fails on 98bd925 |

Offline tests do not prove e-mail delivery or real Zabbix compatibility, and this document does not claim either.

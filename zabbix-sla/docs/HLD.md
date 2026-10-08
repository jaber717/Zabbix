# Zabbix Enterprise SLA & Service Assurance - High-Level Design (proposal)

Status: **proposal + LAB implementation (offline-tested, 131 automated tests)**. Nothing here has been applied to a live Zabbix; the platform is NOT production-ready until the independent live acceptance (ACCEPTANCE-MATRIX.md) has passed. Production is out of scope until approval.
Project: `zabbix-sla/` (independent of `zabbix-alerting/`, which stays at its published release `v1.0.1` and is *reused*, not modified).

## 1. What is measured, and what is not

Device uptime answers "is the box alive". The business asks "can site X reach what it needs". The platform therefore reports three **tiers**, never mixed into one unqualified number:

| Tier | Question | Evidence | Zabbix object |
|---|---|---|---|
| T1 Infrastructure | Is each component (link, later device) up? | Existing NETOPS link-down problems (both ends of every link alert) | leaf services with problem tags |
| T2 Path | Is there at least one working composition of components? | T1 composed in series (path) and parallel (redundancy) | service tree algorithms |
| T3 Verified end-to-end | Does traffic actually flow over the intended path to the real destination? | Active Assurance probes with routing proof | probe-signal services |

Each business SLA states its tier. An SLA built only on T1/T2 is labelled **"inferred - not verified end to end"**; T3 is the only tier that may be labelled "verified service availability". A link can be up/up while BGP or the far side is dead, so T1/T2 can over-state availability; T3 exists to catch that.

### Non-negotiable semantics
1. **Utilization is not downtime.** Service problem tags match only availability signals (`netops_alert=link_down`, probe signals). `util_rx/util_tx/errors/discards/flapping` never reach the service tree; they appear in the monitoring-quality and capacity views.
2. **No data is never 100 %.** Zabbix reports a service with no problems as OK. Every SLI is therefore *qualified* by an independent data-coverage check (probe freshness, signal-source existence, item coverage). Result states: `COMPLIANT`, `BREACHED`, `INSUFFICIENT_DATA` (never a bare 100 %). A service with no verifiable signal source fails `check` and cannot be applied.
3. **Redundancy is modelled, not assumed.** A redundant service is down only if *all* its independent paths are down (parallel); a path is down if *any* of its components is down (series). National fallback through the international transit exists in the model **only** when the inventory marks it `verified: true` with evidence; the default is `false`.
4. **ISP-path measurements are not provider SLA claims.** Our probes measure our path from our vantage point. Provider contractual SLAs (their scope, exclusions, measurement point) are recorded separately in the inventory (`provider_sla`) and shown side by side, never merged; a report never writes "provider X breached SLA" - only "our measured path availability was Y".
5. **Planned downtime is policy, not an edit.** Excluded downtime is a reviewed YAML entry (ticket, approver, window, cap) applied to the SLA, listed in every report. Closed months are immutable: the planner refuses to add, change or remove an excluded-downtime entry that ended before the current month, and refuses to move an `effective_date` that has been reached.

## 2. Topology facts used (from the Codex hand-off; to be re-verified, see EVIDENCE-REQUESTS.md)

Eleven routed P2P links (`link_id` values already present as event tags): `int-core--stc`, `int-core--mobily`, `stc--site-b`, `mobily--site-a`, `saix-core--saix-a`, `saix-core--saix-b`, `saix-a--site-a`, `saix-b--site-b`, `site-a--site-b`, `site-a--palo-transit-a`, `site-b--palo-transit-b`.

```text
          INT-CORE ──── STC ───────────┐                 International
              └──────── MOBILY ──┐     │
                                 │     │
   SITE-A ──mobily--site-a───────┘     └── stc--site-b ── SITE-B
     │ ╲_______ site-a--site-b (inter-edge, iBGP) ________╱ │
     │                                                      │
   saix-a--site-a                                    saix-b--site-b          National
     └── SAIX-A ── SAIX-CORE ── SAIX-B ──┘
   SITE-A/SITE-B ── palo-transit-a/b ── PALO-LAB (firewall/edge)   (role to be confirmed)
```

Redundancy implied by topology (each *to be proven by failure injection*, not assumed):

| Service | Primary | Alternate | Fallback through transit? |
|---|---|---|---|
| SITE-A International | SITE-A → MOBILY → INT-CORE | SITE-A → inter-edge → SITE-B → STC → INT-CORE | n/a |
| SITE-B International | SITE-B → STC → INT-CORE | SITE-B → inter-edge → SITE-A → MOBILY → INT-CORE | n/a |
| SITE-A National | SITE-A → SAIX-A → SAIX-CORE | SITE-A → inter-edge → SITE-B → SAIX-B → SAIX-CORE | **unverified - modelled absent** |
| SITE-B National | SITE-B → SAIX-B → SAIX-CORE | SITE-B → inter-edge → SITE-A → SAIX-A → SAIX-CORE | **unverified - modelled absent** |

## 3. Service model

Hierarchy (service tree; names and ids come from YAML, one stable `sla_id` tag per service):

```text
L4 Business   Site-A Internet access │ Site-A National access │ App <X> at Site-A │ (same for Site-B) │ Inter-site connectivity
L3 Connectivity (parallel)   conn.siteA.international = path.siteA.intl.mobily ∥ path.siteA.intl.stc-via-siteB
L2 Path (series)             path.siteA.intl.mobily = link:mobily--site-a ⊕ link:int-core--mobily   (+ probe:P-intl-A for T3)
L1 Component (leaf)          link:<link_id>  (problem tags: link_id=<id>, netops_alert=link_down)
T3 Probe (leaf)              probe:<id>      (problem tag: sla_probe=<id>)
Monitoring quality (not in any SLA)  quality.* (probe stale, signal source missing)
```

* Series = algorithm `most critical of child services`; parallel = `most critical if all children have problems`. Parent status never "improves" past its algorithm.
* A leaf can have several parents (a link belongs to several paths) - the tree is a DAG, which Zabbix supports.
* **Combining T2 and T3 for one business service:** the business service has two children: the inferred composition and the verified probe set, combined in *series* for the verified SLA ("must be up by both views") and reported separately for the inferred SLA. This is deliberate: a green T2 with a red probe is the exact failure the platform exists to expose.

### Why the Zabbix problem-tag matching rule is the first unknown
Leaves need two tags to be true at once (`link_id` and `netops_alert=link_down`) so that utilization alerts on the same link do not count. Whether Zabbix 7.0 combines multiple service problem tags with AND or OR is **not established**; the design assumes AND only after the acceptance test `scripts/accept_tag_semantics.py` proves it live (Phase 1 gate). If it is OR, the contingency is SLA-owned *signal triggers* (one trigger per link carrying a single unique tag); the engine's `signals:` abstraction already isolates this choice.

## 4. Tag taxonomy

Audit of the LAB (`evidence/tag-audit-lab.json`, read-only, 2026-10-08): no services, no SLAs; host groups = only "Discovered hosts"; host tags exist only for 4 NetBox-synced mock hosts; WAN routers have **no host tags**. Existing event/trigger tags: stock `scope` (availability/performance/notice/capacity/security), `class`, `component`, `target`; NETOPS `netops_alert`, `if_name`, `if_descr`, `if_role`, `link_id`, `site`, `direction`, `threshold`, `severity_label`; media adds volatile `__telegram_msg_id_*`.

Findings that shape the proposal:
1. `link_id` is clean and unique per link: the T1 key. `netops_alert` cleanly separates `link_down` from `util_*`.
2. NETOPS `site` is not a site identifier (value `WAN-LAB` for most routers): **services must not be tied to the `site` problem tag**; site membership is expressed by *service tags*, not by matching problems.
3. `scope=availability` (stock) exists but is not host-specific, so it can only qualify a signal, never identify a component.
4. Volatile tags (`__telegram_*`, `threshold` values, macro-valued tags) must never appear in a service condition.

New tags introduced (all namespaced, none modifies an existing tag):

| Object | Tag | Meaning |
|---|---|---|
| Service | `managed_by=zabbix-sla` | ownership marker (required for any change) |
| Service | `sla_id=<yaml-id>` | stable identity; names may change |
| Service | `layer=component|path|connectivity|business|probe|quality` | tree layer |
| Service | `site=SITE-A|SITE-B|INTER-SITE`, `provider=STC|MOBILY|SAIX`, `tier=T1|T2|T3`, `sla_class=<id>` | grouping / SLA selection |
| Problem (probe triggers) | `sla_probe=<probe id>` (down), `sla_probe_stale=<probe id>` (no fresh data) | the only probe-signal tags; owned by this project; one tag per signal |
| Probe items/triggers | `managed_by=zabbix-sla` | ownership |

Host tags are **not** added in Phase 1 (NetBox sync behaviour unknown; see evidence). A device-level layer is Phase 3.

## 5. SLA objects and SLO policy

* One Zabbix SLA per class (`sla_class`), period **monthly**, timezone `Asia/Riyadh`, schedule 24×7 unless the inventory says otherwise, `effective_date` fixed in YAML (never "today").
* SLOs are inventory values with a documented source (contract, internal target). Defaults in YAML are placeholders marked `approved: false`; `apply` refuses to create an SLA whose `approved` is not true in Production.
* SLI/SLO/error budget are read with `sla.getsli`; the platform adds: coverage qualification (rule 2), burn rate (downtime rate ÷ the rate the SLO allows; above 1.0 the budget runs out early), remaining error budget, and the excluded (planned) downtime shown separately. A breach is reported as certain when recorded downtime already exceeds the whole budget, even if data is incomplete.
* Quarterly/annual views are computed by the report from monthly results; they are not separate Zabbix SLAs in Phase 1.

## 6. Active Assurance (T3)

A probe = a *runner* (a Zabbix host/proxy at a defined vantage point) + **N destinations** + quorum **K-of-N** + **routing proof**.

* Items per destination: `icmpping`/`icmppingloss`/`icmppingsec` or `net.tcp.service` simple checks; one calculated item `sla.probe.up[<id>]` = number of destinations answering; trigger `up < K` → problem tagged `sla_probe=<id>`.
* **Freshness:** `nodata(sla.probe.up[<id>], {$SLA.STALE})` → problem tagged `sla_probe_stale=<id>`, mapped to a *quality* service. It is not downtime, but the internal `data-freshness` SLA measures how long it lasted and a T3 figure with more than 2 % stale time is reported `INSUFFICIENT_DATA`. Each signal has its own single tag, so probe services do not depend on the AND/OR question.
* **Routing proof** (mandatory field `verification`): `pinned_destination` (destination only advertised over the intended path, so success implies the path), `source_pbr` (runner source address policy-routed over the path), `traceroute` (hop evidence, gated), or `none`. A probe with `none` is labelled *reachability only* and **cannot** feed a path service or a verified SLA (validation error).
* Multiple destinations per path (≥ 2, ideally across independent upstream networks) so one far-end outage does not look like a path outage; K is set explicitly per probe (1 ≤ K ≤ N) and reviewed; there is no default.
* Probes are created through the Zabbix API as host-level objects with ownership tags (no template needed); readback verifies items, formula and trigger expressions.
* Which runner can reach which destination, and which source addresses exist, is **unknown** (EVIDENCE-REQUESTS.md E-04..E-07). Probe definitions in the LAB inventory are therefore marked `status: proposed` and are not applied until Codex confirms addresses and runners.

## 7. Reporting and dashboards

* **Reporting integration (no duplication):** `slaas report` emits a JSON report `zabbix-sla-report-v1` (SLI, SLO, error budget, burn rate, qualification, excluded downtime, link-signal quality, provider-claim note, evidence tier) and, with `--suite-doc`, the same content as a document in the `zabbix-reporting-suite-report-v1` model. The existing PDF/XLSX/JSON renderers consume the document; this project contains no renderer. The one hook needed on the reporting side is "render a supplied document" (see INTEGRATION-REPORTING.md).
* **Dashboards:** native Zabbix dashboards defined as YAML (`dashboards/*.yaml`) and provisioned by `dashboard.create/update`: *Executive* (SLA report widgets, monitoring-data-quality problems) and *NOC* (link-down, probe-failure and stale-probe problem lists, SLA report). The service tree itself is the native Monitoring → Services page; Zabbix has no service-tree widget. Widget field type ids differ by build; Phase 4 starts with Codex exporting one hand-built dashboard so the type table is taken from the real server.

## 8. Environment safety, apply, drift, rollback

* Separate inventories `inventory/lab.yaml` and `inventory/production.yaml`; each declares `environment:`; selection by `--env` only; the production file ships **empty**.
* Identity: reuses the `{$NETOPS.ENVIRONMENT}` global macro and URL guards from `zabbix-alerting` (imported, not copied): a LAB invocation against a server that identifies as production is refused; production writes need `--confirm production`.
* Pipeline: `check` (offline inventory validation; no Zabbix contact) → `plan` (read-only CREATE/UPDATE/orphan list with semantic drift) → `apply` (backup, ordered journalled writes, automatic readback verification) → `verify` (drift check, exit 2 on drift) → `rollback` (restore from a backup, itself backed up first). `quality` checks that every link has a working availability signal; `report` produces the monthly figures.
* **Semantic drift:** compare normalized meaning (service identity by `sla_id` tag; parents/children by identity not id; problem tags and status rules as sets; SLA conditions as sets; probe formulas whitespace-insensitively). Internal ids never count as drift.
* **Ownership:** only objects carrying `managed_by=zabbix-sla` are changed or removed; same-named foreign objects are `REVIEW REQUIRED`.
* **Rollback:** the backup stores, per touched object, its prior full definition (or "absent"); rollback recreates/restores/deletes accordingly and is tested against the Zabbix API model including partial-failure recovery. It is not claimed for production until Codex exercises it live.
* No database access; only supported API methods (`service.*`, `sla.*`, `host.get`, `item.*`, `trigger.*`, `dashboard.*`, `usermacro.*` read, `configuration.*` read).

## 9. Phases

See [PHASED-PLAN.md](PHASED-PLAN.md). Implemented offline in this delivery: Phases 0-5 as code (engine, services, SLAs, drift, apply, rollback, evaluator, probe generation, SLO reporting with qualification, planned-downtime policy, reporting bridge, dashboard generator, live-acceptance helpers). None of it has touched a live server. Gated on Codex evidence: live acceptance of every API assumption, probe activation, dashboard provisioning, production.

## 10. Risks

| Risk | Mitigation |
|---|---|
| Problem-tag AND/OR semantics differ from assumption | Phase-1 gate test; contingency design (owned signal triggers) |
| Link-up/BGP-down looks like uptime | T3 probes; labelled inferred tier |
| Unmonitored far ends (SAIX-CORE, PALO-LAB) | `signal_coverage` warning per component; reported as limitation |
| Probe runner cannot reach destinations / no PBR | probes remain `proposed`; SLA stays inferred |
| nbzsync/NetBox sync rewrites tags | no host tags in Phase 1; evidence E-09 |
| Service/SLA API differences on 7.0.30 | acceptance matrix + Codex live run; mock mirrors documented validation only |

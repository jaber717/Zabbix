# Low-level design

Everything below is implemented in `zabbix-sla/slaas/` and covered by `tests/` (131 tests, Python 3.12 on the VM; syntax checked against the 3.8 grammar, runtime needs 3.9+ for `zoneinfo`).

## 1. Module map

| Module | Responsibility | Pure? |
|---|---|---|
| `_compat.py` | Imports the published `netalert` package (`ZabbixClient`, `HttpTransport`, `envsafety`, `UniqueKeyLoader`, errors) from `../zabbix-alerting` via `sys.path`. Imported, never copied or modified. | - |
| `client.py` | `SlaClient`: `ZabbixClient` plus `sla.getsli` as an explicit extra read method. netalert's guard is a whitelist (`*.get` only), so `sla.getsli` was refused as a write; every other non-get method remains a write. | - |
| `env.py` | Environment file loading, the three identity locks, `open_client`, production gate. | no |
| `tags.py` | Tag constants and rules (ownership, forbidden condition tags, name prefix). | yes |
| `inventory.py` | Strict YAML inventory validator (`validate`) - unknown keys, references, cycles, probe rules, SLO/approval, planned-downtime policy, the `tag_semantics` gate. | yes |
| `model.py` | `compile_inventory`: inventory → `Desired` (services, SLAs, active probes, deferred list, notes). `probe_objects`: items/triggers a probe needs. | yes |
| `evaluator.py` | Offline status evaluation of the compiled tree (Zabbix algorithms) for tests and `simulate`. | yes |
| `state.py` | One normalised JSON-safe shape for desired / live / backup state; `read_live` (read-only); field comparison table. | reads |
| `planner.py` | `diff` (pure) and `build` (reads, then diffs): CREATE / UPDATE / orphan / DELETE, conflicts, closed-month immutability. | diff pure |
| `apply.py` | Backup, ordered journalled execution, readback verification, rollback. | writes |
| `slo.py` | SLI/SLO/error-budget math and qualification; link and service signal quality. | yes |
| `reporting.py` | `quality` and `report`: reads `sla.getsli`, `trigger.get`, builds the monthly report. | reads |
| `bridge.py` | Report → `zabbix-reporting-suite-report-v1` document (no renderer). | yes |
| `dashboards.py` | YAML → `dashboard.*` objects, drift, evidence-gated apply. | reads/writes |
| `acceptance.py` | Live acceptance helpers (tag semantics, API shapes). | writes (LAB) |
| `cli.py` | `sla.sh` commands, exit codes, banner. | - |

## 2. Inventory → objects

| Inventory | Zabbix object | Algorithm | Problem tags |
|---|---|---|---|
| `components.<id>` (`kind: link`, `link_id`) | service `NETOPS-SLA: Link <link_id>` | series (2) | `link_id = <id>` AND `netops_alert = link_down` (only when `tag_semantics: and`) |
| `paths.<id>` | service | series (2) over its components | - |
| `connectivity.<id>` (`parallel`/`series`) | service | parallel (1) over included members, else series | - |
| `business.<id>` | service (T2 inferred / T3 verified) | series over `requires`; `redundancy: parallel` allowed | - |
| `probes.<id>` (`active`) | services `probe.<id>` and `quality.<id>` + host items/trigger | series | `sla_probe=<id>` / `sla_probe_stale=<id>` (one tag each) |
| (generated) | `root`, `quality.root` | series | - |
| `slas.<class>` | SLA `NETOPS-SLA: <title>`, monthly, 24x7, `service_tags: sla_class=<class>` | - | - |
| (generated) | SLA `data-freshness` (`service_tags: layer=quality`), only when a probe is active | - | - |

Every service carries tags `managed_by=zabbix-sla`, `sla_id=<id>`, `layer`, and (where known) `site`, `provider`, `tier`, `sla_class`. Identity is the `sla_id` tag, never the Zabbix id or the name.

Rules enforced at compile time: a `proposed` probe and everything depending on it are *deferred* (reported, not applied); a link service is not emitted at all unless `tag_semantics: and`; an unverified `fallback_via_transit` member is excluded with a note; a `parallel` connectivity with a single included member degrades to series with the note "NO redundancy is represented".

## 3. State, diff and ownership

`state.py` normalises three sources into the same dictionary:

```text
{"services": {sla_id: {name, algorithm, description, tags[[k,v]], problem_tags[[k,op,v]], children[sla_id]}},
 "slas":     {class:   {name, slo, period, timezone, status, effective_date, description, service_tags, schedule, excluded_downtimes}},
 "items":    {"host|key": {name, type, value_type, delay, params, tags}},
 "triggers": {"host|description": {expression, priority, tags}}}
```

Keys starting with `_` (Zabbix ids, foreign children, host names) are bookkeeping and never compared. Children are compared as sets of `sla_id`; children that are *not* managed (added by a person) are neither drift nor removed - they are re-sent unchanged whenever the managed children are rewritten.

Ownership: services/items/triggers by tag `managed_by=zabbix-sla`; SLAs by the description marker `managed_by=zabbix-sla sla_id=<class>`. A same-named unmanaged object is a **conflict** (blocks apply), never adopted. Managed objects missing from the inventory are *orphans*: listed, kept, removed only with `--prune`.

Additional planner rules (all produce conflicts, i.e. block apply): runner host of an active probe must exist; an SLA whose SLO is `approved: false` is refused in production; excluded downtime that ended before the current month cannot be added, changed or removed, and a reached `effective_date` cannot move (closed periods are immutable).

## 4. Apply order and journal

1. Probe items (calculated item last), probe triggers.
2. Services: create bare → update changed fields → re-link children (`service.update children`) once every id is known.
3. SLAs.
4. Deletions (only with `--prune`): SLAs, triggers, items, services.

Before step 1 a backup (`state/backups/<env>-<UTC>.json`, mode 0600) stores the whole pre-apply managed state plus the planned lines; each API step is appended to `state/journal/<env>-<UTC>.jsonl` (success or failure with the error text). The state directory is ignored by Git. No secret is ever written (tokens live only in the environment).

After the last step the planner runs again with the same inputs; any remaining difference is reported as **READBACK VERIFICATION FAILED** with the backup path, exit code 1.

## 5. Rollback

A backup is a target state. `rollback --backup F` builds the plan "live → state in F" with prune on, takes a new *pre-rollback* backup (so rollback itself is reversible), executes with the same engine and re-verifies. Objects are matched by identity (`sla_id`, class, host+key), so objects deleted by the failed run are recreated and objects created by it are removed. Zabbix ids of recreated objects change (documented consequence for saved links/dashboards). Foreign objects are never touched. Partial failure is the normal rollback case: the CLI prints the exact `rollback --backup` command.

## 6. Environment locks (`env.py`)

1. `--env` selects `config/environments/<env>.yaml`, which names its inventory; the inventory must declare the same `environment:` or the run is refused.
2. URL guards from `envsafety` (`url_regex`, `forbid_url_regex`, not another environment's target).
3. Server identity: global macro `{$NETOPS.ENVIRONMENT}` must equal `--env`. This project never creates it; writes need identity state `ok`. A missing macro allows read-only commands only.
4. Production: `--confirm production`, checked **before** the server is contacted.
5. `--assume-tag-semantics and` is accepted only by `plan`/`check`/`simulate`; `apply` and every write path reject it, and the plan banner says the result is not authoritative.

## 7. Probes (T3)

Per destination one simple-check item (`icmpping[addr,3,200,,1000]` or `net.tcp.service[tcp,addr,port]`) on the runner host; one calculated item `sla.probe.up[<id>]` = `last(//k1)+last(//k2)+...`; trigger `last(/host/sla.probe.up[<id>])<K` (severity default disaster) tagged `sla_probe=<id>`; trigger `nodata(/host/sla.probe.up[<id>],<stale_after>)=1` (warning) tagged `sla_probe_stale=<id>`. All objects tagged `managed_by=zabbix-sla`; trigger names start with `[NETOPS-SLA] `. They deliberately carry **no** `netops_alert` tag, so the NETOPS Telegram action never fires for them. Whether `icmpping` returns a plain 0/1 usable in the formula, whether a simple check wants an `interfaceid`, and whether `nodata()` on a calculated item behaves as designed are acceptance items (A-16).

## 8. SLI qualification (`slo.py`)

Inputs per service/month: the `sla.getsli` cell, the SLO, period seconds, *window* seconds (period ∩ [effective_date, now]), signal quality, probe stale seconds, caveats.

```text
coverage = (uptime + downtime + excluded) / window
INSUFFICIENT_DATA if: no SLI | coverage < 98% | signal blind | (T3 and stale unknown or > 2% of window)
BREACHED          if: downtime > whole-period budget (certain, even when data is incomplete) | SLI < SLO
COMPLIANT         otherwise;  partial signal adds a caveat, an unapproved SLO adds "placeholder"
budget_total = period x (1 - SLO);  remaining = total - downtime;  burn = (downtime / counted) / (1 - SLO)
```

An `INSUFFICIENT_DATA` row exposes `sli_pct_reportable = null`; the document shows N/A, never a number. Signal quality comes from `trigger.get` on `link_id` + `netops_alert=link_down`: no trigger → `MISSING`, all disabled → `DISABLED`, all unknown/error → `UNKNOWN` (these three = `blind`), fewer working ends than expected → `PARTIAL`.

## 9. Dashboards

`dashboards/*.yaml` → normalised dashboard → `dashboard.create/update`. Services and SLAs are referenced by `sla_id`/class and resolved to ids at plan time; an unknown reference is reported and the dashboard skipped. Field type ids and names come from `evidence/widget-field-types.json` (written by `scripts/accept_widget_fields.py` from a hand-built LAB dashboard, matched by the values the tester entered); without it the generator uses marked-UNVERIFIED defaults and `apply` is refused. Dashboards are owned by name prefix `NETOPS-SLA: `; other dashboards are never changed.

## 10. Failure behaviour

| Condition | Result |
|---|---|
| Inventory invalid / wrong environment | exit 1, "nothing was contacted" |
| Identity mismatch, bad URL, wrong token, unreadable API | exit 1, no write |
| Plan has conflicts | exit 1, no write |
| API error mid-apply | exit 1, journal + backup path + rollback command printed |
| Readback differs | exit 1, backup path printed |
| Drift found by `verify` | exit 2 |
| `quality` finds a degraded signal | exit 2 |

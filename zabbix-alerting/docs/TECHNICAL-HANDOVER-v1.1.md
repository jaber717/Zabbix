# Verified technical handover — Zabbix Alerting (`zabbix-alerting/`), before and after v1.1.0 onboarding

Reconstructed on 2026-11-11 from the repository only (all branches and tags fetched, no PRs exist). Nothing below comes
from memory of earlier sessions without a repository source. LAB and Production were **not** accessed.

## 1. Repository structure and versions

| Ref | Commit | State | Source |
|---|---|---|---|
| default branch `staging` | `9d6a996` (2026-09-20) | **does not contain `zabbix-alerting/`** | `git ls-tree origin/staging` |
| `main` | — | does not contain `zabbix-alerting/` | same |
| tag `v1.0.0`, `v1.0.1` | `9f0244b`, `489080d` | superseded (v1.0.1 failed acceptance: `scripts/ingest-handover.py` did not compile) | `RELEASE-v1.0.1.md`, `docs/DESIGN.md` |
| tag **`v1.0.2`** (annotated `e30181a`) | **`855cd32`** | **only accepted release** ("APPROVED WITH LIMITATIONS") | tag annotation; `handover/agents/codex-v1.0.2-final-lab-acceptance.md` (commit `4260b13`, now cherry-picked here as `c60732b`) |
| `claude/interface-alerting-v1.0.2-production-review` | `1b53026` | docs only: production review + offline bundle install | `docs/CLAUDE-FINAL-PRODUCTION-REVIEW.md` |
| `claude/ospf-neighbor-monitoring-v1.0.3` | `f55be55` | v1.0.3 proposal: Network Health, **untested**, not tagged | `RELEASE-v1.0.3.md` |
| **`claude/discovery-onboarding-v1.1`** (this branch) | on top of `f55be55` | v1.1.0 candidate: discovery-assisted onboarding | `RELEASE-v1.1.0.md` |

Implemented ≠ tested ≠ released ≠ merged ≠ deployed: nothing of `zabbix-alerting/` is merged into `staging`/`main`, the
only release is the `v1.0.2` tag, and **no production deployment exists** (no evidence in any branch).

Layout: `apply.sh` → `netalert/` (Interface Alerting: `config.py` strict schema, `planner.py` read/plan, `apply.py`
writes, `template.py` generated template, `envsafety.py` identity/URL/production gate, `zbx.py` client, `handover.py`
+ `scripts/ingest-handover.py` handover verification); `apply-health.sh` → `nethealth/` (Network Health);
`config/` inventories and environments; `tests/` offline suite with `fake_zabbix.py` (in-memory Zabbix 7.0 model);
repository-root `handover/` holds the Codex LAB handover (`p2p-interfaces.yaml`, `agents/codex-latest.md`).

## 2. Features implemented

| Feature | Where |
|---|---|
| Interface Alerting: link down/up, RX/TX utilization with hysteresis, errors, discards, flapping, speed-below-expected; per-interface severity, role, `link_id` | `netalert/template.py` (`trigger_prototypes`, alerts `link_down`, `util_rx`, `util_tx`, `errors`, `discards`, `flapping`, `speed_degraded`), `netalert/model.py:host_macros` |
| Strict YAML (unknown/duplicate keys, `notify` rejected) | `netalert/config.py` (`UniqueKeyLoader`, `normalize_interface`) |
| Identity macro, URL guards, `--confirm production`, read-only check/dry-run client | `netalert/envsafety.py:verify`, `production_gate`; `netalert/zbx.py:ZabbixClient(read_only)` |
| Ownership (`managed_by=zabbix-alerting-as-code`), drift detection, backups, VERIFICATION INCOMPLETE | `planner.py`, `backup.py`, `cli.py` |
| E-mail/Telegram action `NETOPS-IaC …` filtered on tag `netops_alert` | `model.py:desired_action`, `planner.py:action_params` |
| Handover verification (Codex format) → YAML + REVIEW-REQUIRED | `netalert/handover.py`, `scripts/ingest-handover.py` |
| Network Health (OSPF, BGP, unreachable, stale, CPU, memory), `{$NHEALTH.*}` namespace | `nethealth/` (v1.0.3) |
| **New:** read-only discovery, NetBox enrichment, onboarding review, generation of both inventories, coverage audit, deploy gate | `netalert/discovery.py`, `netbox.py`, `onboarding.py`, `review.py`, `coverage.py`, `onboard_cli.py`, `onboard.sh` |

## 3. Features actually validated (evidence)

| Claim | Evidence type | Source |
|---|---|---|
| Real LAB (Zabbix 7.0.30, 7 routers, 18 P2P interfaces): import, apply, 18/18 fresh, idempotent dry-run | **live LAB, historical** | `handover/agents/codex-latest.md` (root), `zabbix-alerting/handover/agents/codex-v1.0.1-final-lab-acceptance.md` |
| Link Down → Problem (event 10865) and Recovery; RX/TX utilization hysteresis (temporary 0.05/0.02 %) | live LAB, historical | `handover/agents/codex-latest.md` "Real event tests" |
| Telegram Problem + Recovery delivered, action filter isolation | live LAB, historical | same file, "Telegram LAB delivery COMPLETE" (branch `codex/interface-alerting-telegram`) |
| v1.0.2 exact commit: `--check` 18/18, dry-run "No changes required." | live LAB, historical | `codex-v1.0.2-final-lab-acceptance.md` |
| Offline suite | executed now: **228 tests PASS on Python 3.13.17 and 3.9.25** (182 existing + 46 new) | `tests/` |
| Release gate (syntax, tests, secret scan, ShellCheck) | executed now: **PASS** (after the SC2164 fix below) | `scripts/release-gate.sh` |

These are historical LAB results and offline results. **None of them proves Production readiness.**

## 4. Not tested / incomplete

* E-mail Problem/Recovery delivery: never executed on any Zabbix (LAB SMTP was not configured) — `codex-latest.md` "Notifications".
* Flapping, error-rate, discard-rate, speed-degraded: never fault-injected live (logic tested offline only).
* Live rollback: never executed.
* Network Health (v1.0.3): no live test at all; its template import is also **rejected by the offline model**
  (`tests/fake_zabbix.py` does not model template `valuemaps`), so even the import path is unexercised.
* Onboarding (v1.1.0): offline only, against `tests/discovery_fixture.py`, which was written from the Zabbix 7.0 API
  documentation (item key/tag conventions of the stock templates, `selectHostGroups`, `selectHostGroupRights`, user media
  severity bitmask). These conventions must be confirmed on the real server (gate 1 in `docs/ONBOARDING.md` §8).

## 5. The manual YAML workflow and why it blocked production

`OPERATOR-GUIDE.md` "Add an interface": per interface an engineer must type the exact Zabbix host name, the exact
interface name as Zabbix tags it, description, role, severity, thresholds, and the same `link_id` on both ends, then
check/dry-run/apply; Network Health needs a second file. In LAB this took a 452-line Codex handover
(`handover/p2p-interfaces.yaml`) plus `ingest-handover.py` for 18 interfaces. Production has its own, larger estate and
started from `hosts: {}` (`config/interfaces.production.yaml`); there was no tool to *find* the interfaces, only to
verify a list someone else produced. Errors were caught (fail-closed checks), but nothing reduced the typing.

## 6. Existing discovery / handover capability (before v1.1.0)

`scripts/ingest-handover.py` + `netalert/handover.py` do **not** discover. They take an externally produced file
(Codex format or a flat list), verify each entry live with `planner.run_checks` (host exists/enabled/SNMP, interface
name present via the `interface` item tag) and `handover.cross_check` (host id, status item id, its `interface` tag,
SNMP index), write verified entries to YAML and the rest to `REVIEW-REQUIRED.md`. Read-only; LAB-oriented (default
`--env lab`, header "LAB policy").

## 7. Reused components (no rewrite)

| Component | Reused for |
|---|---|
| `zbx.ZabbixClient(read_only=True)` | every discovery/verify read; a write raises `ReadOnlyViolation` before sending (mutation-tested) |
| `envsafety.load_env/verify/production_gate/normalize_url` | identity, URL guards, production confirmation, setup's URL guard |
| `handover.cross_check` | deploy gate: host id / status item / interface tag / SNMP index drift since approval |
| `planner.get_hosts`, `planner.run_checks` (inside `apply.sh --dry-run`) | live verification of the generated inventory |
| `config.parse/load_file/UniqueKeyLoader`, `nethealth.config.parse` | strict validation of every generated file before it is written |
| `cli.run` (`apply.sh`) and `nethealth.cli.run` | the only write path at deploy time, unchanged |
| `tests/fake_zabbix.MockZabbix` | base class of `tests/discovery_fixture.py`; the real apply path runs in the same tests |

## 8. What was missing for production automation (now added on this branch)

Read-only discovery of ports from stock interface items; freshness/unsupported detection; candidate suggestion with
evidence; operator decisions persisted across runs; preservation of existing entries; verified-only pairing (NetBox
cable or operator confirmation); deterministic generation of both inventories; coverage audit that checks notification
readiness end-to-end; a deploy gate that fails closed on stale/unresolved/unapproved state; GitHub-direct install on RHEL.

## 9. Compatibility risks

1. Stock template conventions (`net.if.status[...]` keys, `interface` tag, ifAlias source) are assumed from Zabbix 7.0
   templates; a vendor template with other conventions yields no ports for that host (reported as a blind spot, never guessed).
2. Template-level tags and time-period action conditions are not evaluated: coverage can be *under*-reported, never over-claimed.
3. A least-privilege token without user/user-group read makes every notification path UNVERIFIED (reported).
4. Hosts in both inventories: coexistence relies on separate namespaces (`{$NETOPS.*}` vs `{$NHEALTH.*}`, different
   markers and templates) — unit-tested only.
5. `ifIndex` changes after reboot (no `ifindex persist`) block deployment until re-approved — intentional.
6. Discovery reads every `interface`-tagged item of the hosts in scope; on very large estates use `--group`.

## 10. Minimum changes made (v1.1.0 candidate)

* New modules only: `netalert/{discovery,netbox,onboarding,review,coverage,onboard_cli}.py`, `onboard.sh`.
* No change to Interface Alerting logic, template, schema, planner, applier or environments; no change to `nethealth/`.
* `scripts/secrets-scan.sh`, `scripts/lab-write-test.sh`: `cd … || exit 2` (3 × SC2164) so the release gate passes when ShellCheck is installed.
* Tests: `tests/discovery_fixture.py`, `tests/test_onboarding.py` (46 tests).
* Docs: `docs/ONBOARDING.md`, this file, `RELEASE-v1.1.0.md`, `examples/onboarding-rules.example.yaml`, short pointers in README/OPERATOR-GUIDE/PRODUCTION-INSTALL.

## Contradictions between documentation and repository state

| # | Document says | Repository shows |
|---|---|---|
| 1 | the project is described as "the repository" (`README.md`) | default branch `staging` has no `zabbix-alerting/`; installs work only because `PRODUCTION-INSTALL.md` line 12 checks out tag `v1.0.2` — a plain clone or `git pull` of the default branch gets nothing |
| 2 | `scripts/release-gate.sh` is "the" release gate; tag `v1.0.2` says ShellCheck "not run" | with ShellCheck installed the gate **FAILS** on `v1.0.2`/`v1.0.3` (3 × SC2164) — fixed here |
| 3 | `RELEASE-v1.0.2.md` line 3: "CANDIDATE. Not published, not tagged" | tag `v1.0.2` and a GitHub Release exist |
| 4 | `README.md` line 54: "only one end has `notify: true`" | `config.py` rejects `notify` (line 39 of the same README says so) |
| 5 | `docs/DESIGN.md` line 88: `alert_action` "stays unset in `lab.yaml`" | `config/environments/lab.yaml` defines a Telegram action |
| 6 | `docs/DESIGN.md` line 84: "all seven routers currently fail SNMPv3 authentication" | `handover/agents/codex-latest.md`: SNMPv3 fixed, 18/18 fresh |
| 7 | `docs/DESIGN.md` line 67: `./scripts/ingest-handover.py handover/p2p-interfaces.yaml` | the file is at repository-root `handover/`, i.e. `../handover/…` from `zabbix-alerting/` |
| 8 | `scripts/ingest-handover.py` header "LAB policy" | same header is written for `--env production` |
| 9 | v1.0.2 accepted on `4260b13` evidence | that record was not in the v1.0.3 lineage (cherry-picked here) |
| 10 | `docs/CLAUDE-FINAL-PRODUCTION-REVIEW.md` C2 / `OFFLINE-INSTALL-v1.0.2.md`: production host has no internet, use a git bundle | current requirement: GitHub-direct from the RHEL VM through the proxy; the bundle method stays valid only for isolated hosts |
| 11 | `RELEASE-v1.0.3.md`: Network Health "syntax only" | still true, plus: its import is rejected by the offline model (no `valuemaps` support) |

Items 3–8 are documentation defects with no behavioural impact; they are listed, not silently rewritten.

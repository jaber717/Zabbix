# Independent acceptance checklist - Hardware Health v0.3.0-rc1 (for Codex)

Run from a clean checkout of the candidate SHA. Record exact command, exit code and output for each line. A line is PASS only with evidence; anything not run is NOT RUN, never PASS. `H="python3.12 hardware_audit.py"`.

## A. Offline (no Zabbix)
| # | Check | Expected |
|---|---|---|
| A1 | `python3.12 -m unittest discover -s tests -t .` three times in a row | OK each time, same test count (no flake) |
| A2 | `python3 ../zabbix-alerting/scripts/check-syntax.py` (copy it under this project's `scripts/`, or run from the repo root) | OK: all Python parse with the 3.8 grammar, all shell `bash -n` |
| A3 | `$H vendors check`, `vendors simulate`, `vendors messages` | exit 0; simulate: 0 failed scenarios |
| A4 | `$H vendors coverage` equals `docs/VENDOR-COVERAGE.md` | identical (also a unit test) |
| A5 | `git diff v1.0.2 -- zabbix-alerting` | empty (Interface Alerting untouched) |
| A6 | Release lifecycle: `release/build-package.sh d/`; `install.sh` to a temp prefix; `verify-deployment.sh`; modify a file under `current/` -> verify fails; `upgrade.sh` keeps config/state; second version -> `rollback.sh` returns to the first; tampered tarball and missing `.sha256` refused | as described |
| A7 | Secret scan of the tree and the package (`grep -rEI '(token|password|secret)\s*[:=]\s*\S{16,}'`) | no credentials |
| A8 | Independently re-derive 3 definitions from the cited official templates/MIB names (pinned commit in each file's `sources`) | OIDs, enumerations, classifications match; flag any mismatch as a defect |

## B. Review of the generated templates (offline, then LAB)
| # | Check | Expected |
|---|---|---|
| B1 | `$H template build --definition cisco-iosxe --out x.json` for every buildable definition | valid JSON, `importcheck` clean |
| B2 | Inspect: no `netops_alert` anywhere; six routing tags on every trigger; alarm triggers have recovery expressions; items feeding `last(#n>1)` do not discard unchanged values; PAN password macro is SECRET_TEXT and empty | true |
| B3 | LAB `template plan` -> `apply` -> inspect in the UI -> `template rollback` | create/applied/deleted; template never linked to any host by the tool; a same-named foreign template is reported as CONFLICT and untouched |
| B4 | After B3 `apply`, link the template to a **throw-away LAB host only if separately approved**; confirm LLD/items/triggers appear and no expression is rejected | (this is the L3 evidence) |

## C. LAB read-only integration (token: LAB only, via environment)
| # | Check | Expected |
|---|---|---|
| C1 | `release/validate-lab.sh <prefix>` | exit 0, prints "no live Telegram delivery was tested" |
| C2 | `$H --env lab labsim` | host 10696, items 52108-52110, triggers 26409-26411 present and delivering; no `netops_alert`; no ENABLED action matches them |
| C3 | `$H --env lab synthetic audit-probe` | AVAILABLE (else negative cases can only be INCONCLUSIVE) |
| C4 | `$H --env lab action plan` | a CREATE of a **disabled** action, or a CONFLICT if one exists; no write happens |
| C5 | Confirm the sim objects are byte-identical before/after the whole run (host/item/trigger/tag snapshot from `labsim`) | no difference |

## D. Needs explicit operator approval (do NOT run without it)
| # | Check | Evidence needed |
|---|---|---|
| D1 | Synthetic notification test, `docs/SYNTHETIC-NOTIFICATION-TEST.md` | PASS verdict for A, B, C with authoritative evidence; `diff` clean |
| D2 | Sim-trigger path, `docs/TELEGRAM-RUNBOOK.md` section 4 Path 2 (tag plan, bounded enablement, `labsim --evidence-since`) | N Problems = N Recoveries, all alerts from the hardware action, none elsewhere; tags restored |
| D3 | Human confirmation of Telegram receipt (Problem and Recovery) and of message content | recorded by operator; only then `config/action-validation.yaml` |

## E. Not available in this release (must remain BLOCKED)
Real-device verification for every vendor; Cisco ASR 8500 and FortiProxy definitions; hardware redundancy sensors; Production. A reviewer finding any of these claimed as done should reject.

## Rejection triggers
A PASS with no authoritative evidence; any write the tool makes outside its own action/template; the hardware action found enabled by the tool; a generated trigger without the routing tags or with `netops_alert`; a coverage cell labelled REAL DEVICE VERIFIED without a `device-evidence.yaml` entry; a changed file under `zabbix-alerting/`.

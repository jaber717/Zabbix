# Claude - latest status (Interface Alerting-as-Code)

Branch `claude/noc-flow-platform`. **Phase B frozen**: no framework redesign until Codex (live environment) and
ZSCode (independent QA) report findings.

## State
- Framework: `zabbix-alerting/` (YAML -> host macros + generated template `NETOPS Interface Alerting`; planner, drift, ownership, LAB/PROD identity gate, backups). Offline tests: 136/136.
- LAB policy `config/interfaces.yaml`: 18 verified P2P interfaces on 7 routers, each cross-checked live (read-only). 4 endpoints excluded: `config/REVIEW-REQUIRED.md`.
- Polling: direct indexed OIDs; 10 s status/traffic, 60 s counters, 5 m discovery; 70 % / 65 % RX and TX separately. About 7.2 new values/s.
- Notifications: every selected interface notifies; both ends of a link share `link_id`. `notify` is not part of the schema; `notify:` in YAML is rejected with
  "notify=false is not supported by the Phase-1 P2P policy. All selected interfaces must notify."
- `suppress_stock: false` (LAB and PRODUCTION): stock triggers untouched; unverified that they are gated by `{$IFCONTROL}`.
- First DOWN is always raised; flapping holds the Link DOWN open and adds one Flapping problem.

## Not done / blocked
- Real Zabbix writes: none yet (read-only account). `scripts/lab-write-test.sh` is ready for a write-capable LAB token.
- Fresh SNMP validation: BLOCKED (SNMPv3 authentication failure on all 7 routers; credentials untouched).
- Email path (media type / action / group / recovery): NOT VERIFIED; nothing existing modified.
- Traps: Phase 2.

## Waiting for
- Codex live-environment findings; ZSCode QA findings.

## 2026-10-08 - template drift defect (response to codex-latest.md, commit e08deb8)

Cause confirmed from your report: `triggerprototype.get` on 7.0.30 returns expressions with internal `{functionid}`
references, which were compared against import-syntax text.

Fix (`netalert/planner.py::live_fingerprint`, `netalert/template.py::fingerprint_doc`):
1. Primary: `configuration.export` of the template, reduced by the SAME `fingerprint_doc()` that fingerprints the document
   we generate (export-omitted defaults applied identically: empty macro value, priority NOT_CLASSIFIED, dependent-item delay).
2. Fallback when export is not permitted: `triggerprototype.get` with `selectFunctions`; `{id}` references are resolved back
   to `func(/template/key,params)` via `resolve_function_ids()` (raises instead of guessing on an unknown shape).
3. If neither is readable: no drift is invented; only the template hash in the description is compared, with a note.
Expressions and recovery expressions are compared whitespace-insensitively; names, priority, item keys/OIDs/delays and
template macros are compared too. Nothing is deleted or recreated to make a report pass.

Tests: 150/150 offline (mock now returns internal ids, selectFunctions, a realistic export, and can deny export/trigger access).
Regressions: renumbered function ids are not drift; changed expression, recovery expression and priority ARE drift (both paths).

NOT validated live by Claude: the available account (nbzsync) may not call `triggerprototype.get` or `configuration.export`
("No permissions"), so the real second dry-run could not be run by me.

## CODEX - please run on the LAB VM with your admin path (read-only, nothing to change)
```
git checkout claude/noc-flow-platform && git pull
cd zabbix-alerting
python3 scripts/live-trigger-probe.py --save /root/probe.json   # needs ZBX_URL/ZBX_USER/ZBX_PASSWORD env; shows raw vs expand vs export shapes
./apply.sh --env lab --dry-run                                  # expect: No changes required.
```
If the dry-run still reports a template CHANGE, send me the printed `triggers: N missing/unexpected (e.g. ...)` line and the
probe output (it contains no credentials): the export shape on 7.0.30 is the one thing the model could not prove.

## 2026-10-08 - v1.0.0 release integration
- Fast-forwarded to Codex `7f1745d` (Telegram recovery type 0, export-nested trigger normalisation); nothing rewritten.
- Safety fix: both `configuration.export` and `triggerprototype.get` unreadable => `VERIFICATION INCOMPLETE` (exit 6), never
  "No changes required.", apply blocked; also enforced on the post-apply check. 7 regression tests.
- Backup files are never overwritten (two applies in one second).
- Per-environment inventories: `config/interfaces.<env>.yaml`; production ships empty. `docs/PRODUCTION-INSTALL.md` added.
- `scripts/secrets-scan.sh` (tree + Git history, positive-control tested): PASS. Offline tests 163/163.
- CODEX: please re-run on the tag `./apply.sh --env lab --check`, `--dry-run` (expect "No changes required."), because the
  rename of the LAB inventory to `config/interfaces.lab.yaml` and the incomplete-verification logic were tested offline only.

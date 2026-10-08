# Release v1.0.2 - Zabbix Interface Alerting-as-Code (hotfix)

**Status: CANDIDATE. Not published, not tagged.** The tag `v1.0.2` is created only after the independent LAB acceptance of the exact candidate commit has passed (see `handover/agents/claude-v1.0.2-candidate.md`).

Supersedes v1.0.1. Install v1.0.2, not v1.0.1 (v1.0.1 failed release acceptance, below). The tags `v1.0.0` and `v1.0.1` are immutable and unchanged.

## Why

Final LAB acceptance of v1.0.1 (Codex, evidence in `handover/agents/codex-v1.0.1-final-lab-acceptance.md`) passed every live check - 18/18 interfaces, 72/72 items, 70/65 thresholds, Telegram, VERIFICATION INCOMPLETE, 175/175 unit tests - but `scripts/ingest-handover.py` did not compile: an unterminated string literal in the generated-policy header (a line break inside a string where `\n` was meant). Release acceptance therefore failed.

## What changed (and nothing else)

| Change | Files |
|---|---|
| **The fix**: `...link_id is shared.<newline>"` -> `...link_id is shared.\n"` (one logical character; the script now compiles, starts, and writes the intended 2-line header) | `scripts/ingest-handover.py` |
| **Regression gate**: `scripts/check-syntax.py` compiles every tracked Python file in the repository (and parses it with the Python 3.8 grammar, the minimum supported) and runs `bash -n` on every tracked shell script; it fails if it finds no Python files, so it cannot pass vacuously | `scripts/check-syntax.py` |
| Gate in the unit suite (7 tests, incl. negative controls proving the gate detects an unterminated string, newer-than-3.8 syntax and a broken shell script, and a `--help` start-up test of the repaired script) | `tests/test_python_syntax.py` |
| One-command release gate: syntax, unit tests, secret scan, ShellCheck (honestly reported as NOT RUN when absent) | `scripts/release-gate.sh` |
| `VERSION` 1.0.1 -> 1.0.2; docs updated | `VERSION`, `docs/PRODUCTION-INSTALL.md`, `docs/DESIGN.md`, `RELEASE-v1.0.1.md` (supersession note), this file |

No change to `netalert/`, the template, the inventories, the Telegram/e-mail configuration or any Zabbix-facing behaviour. `TOOL_VERSION` (which is part of the template hash) is deliberately **not** touched, so a v1.0.1 LAB reports no drift against v1.0.2.

## Gate results for the candidate

See the candidate hand-off file for the exact commit and the transcript summary. Gate: `./scripts/release-gate.sh`.

| Gate | Result |
|---|---|
| Python compile, whole repository (63 files, grammar 3.8+) | PASS (v1.0.1's file FAILS the same gate: negative control) |
| `bash -n`, whole repository (34 scripts) | PASS |
| Unit suite | 182/182 PASS (175 + 7 new) |
| Secret scan: working tree, forbidden files, full history | PASS (no findings) |
| ShellCheck | **NOT RUN** - not installed on the workstation, the LAB VM or the acceptance machine; nothing was downloaded to obtain it. Not a pass. Run `./scripts/release-gate.sh` where `shellcheck` exists; gate 4 then executes automatically at `-S warning`. |
| Real LAB, exact candidate commit | **pending Codex** |

## Rollback status

* Mechanism: inventory-as-code. Restore the previous known-good inventory revision from Git, `./apply.sh --env <env> --dry-run` to inspect, then apply. Every apply first writes `state/backups/<env>-<time>.json` (previous managed state).
* Offline: tested - exact previous-state restoration, removal of only tool-created objects, pre-apply backup, action restoration.
* **Real LAB rollback: NOT TESTED** (not in v1.0.1's acceptance either). Nothing in v1.0.2 changes this. Do not describe rollback as live-verified until a LAB run has changed and restored a managed object.

## Remaining Production deployment limitations

* Production has never been touched or run; `config/interfaces.production.yaml` is intentionally empty; the production URL regex is a fail-closed placeholder that must be set to the real production URL.
* Production needs its own token and an explicit identity initialisation (`--init-identity`) and `--confirm production`.
* E-mail (SMTP) delivery in Production is configuration-only and unverified: media type, user group, action and recovery operation have not been exercised on a real Zabbix. The LAB Telegram path is what was verified, and the LAB bot is temporary (revoke at decommissioning; it is not configured for production).
* An account that can read neither `configuration.export` nor `triggerprototype.get` yields `VERIFICATION INCOMPLETE` (exit 6) and no apply, by design.
* SNMP traps are Phase 2; stock trigger suppression stays off.
* Real LAB rollback and ShellCheck: not exercised (above).

# Handoff to Codex - Hardware Health v0.3.1-rc2

Branch `claude/hardware-health-v0.3.1-rc2` (from the rejected `c1f96cb`; the rejected branch and Codex's `codex/hardware-health-v0.3-rc1-acceptance` are untouched). Tip SHA: the delivery message. **No approval is claimed.**

## What changed (security remediation)
`hwh/tplmgr.py` rewritten; `hwh/template.py` rules (`IMPORT_RULES`, `CREATE_RULES`, `RESTORE_RULES`); CLI override flags removed; `release/*.sh` (reproducible package, private state, ownership check); `hwh/evidence.py` (`auditlog_mode`); PAN-OS definition/template; `docs/sources/*` (MIB and PAN extracts) and conformance tests. Design: `TEMPLATE-MANAGEMENT-DESIGN.md`. Evidence: `ACCEPTANCE-V0.3.1-EVIDENCE.md`. Sources: `VENDOR-SOURCES-REVIEW.md`.

## Please attack
1. The five original sequences, unchanged: `qa/acceptance_v03_security_repro.py` (now stops at the first refusal) and `qa/acceptance_v031_regression.py`.
2. New sequences against `tests/test_v03_tplmgr.py::FakeTpl`: anything that gets `configuration.import` or `template.delete` called on a template this deployment does not demonstrably own, or on a linked one, or that deletes a child.
3. The weak points I know: (a) everything is proven against a fake - the real `configuration.export` byte-stability after canonicalisation is unobserved (checklist B9); (b) `RESTORE_RULES` is the only path with `deleteMissing`; check that its bound (removals <= objects added by the rolled-back operation) holds against a real `importcompare`; (c) identity-based content check ignores field values on purpose (Zabbix normalises them) - drift detection covers values live-vs-live instead; (d) a crash exactly between the import and the first record write after it cannot be recovered by the tool (it refuses).
4. Run the read-only `qa/acceptance_v03_readonly.py template-plan` again: the plan now prints operations, linked host ids and refuses without `importcompare`.

## Honest status
Defects 1-5 fixed and regression-tested offline; no live write was made or is needed to run these checks. Still outstanding and unchanged: real-device evidence (0 cells), a live template import, Telegram delivery, Production.

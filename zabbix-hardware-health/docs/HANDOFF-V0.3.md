# Handoff to Codex - Hardware Health 0.3.0-rc1

Branch: `claude/hardware-health-v0.3-rc` (from v0.2.4 `ca84bde`). The candidate SHA is the branch tip at hand-over (`git rev-parse HEAD`); it is stated in the delivery message because a commit cannot contain its own hash.

## What changed since v0.2.4
New: `vendors/*.yaml` (7 definitions), `hwh/vendordefs.py`, `hwh/expr.py`, `hwh/simulate.py`, `hwh/template.py`, `hwh/importcheck.py`, `hwh/tplmgr.py`, `hwh/labsim.py`, `hwh/messages.py`, `hwh/coverage.py`, `release/*.sh`, `config/lab-sim.yaml`, `config/device-evidence.yaml`, eleven documents.
Modified: `hwh/api.py` (read: `template.get`, `configuration.export`; write only via `write_templates=True`: `configuration.import`, `template.delete`), `hwh/policy.py` (`sensor` category), `hwh/semantics.py` (documentation-derived registry), `hwh/synthetic.py` (new preflight isolation check), `hardware_audit.py` (`--base`, `vendors`, `template`, `labsim`), `config/vendors.yaml`, `docs/COVERAGE-MATRIX.md` (regenerated), README.
Untouched: `zabbix-alerting/` (empty diff against `v1.0.2`).

## Where to attack (my own doubts)
1. Generated template **import acceptance** on 7.0.30 (L3) - please run B3/B4 of the checklist first; any rejection is a defect to report with the exact API error.
2. The **confirm/recover expressions**: is `last(#n)` OR-of-equalities plus recovery-expression semantic exactly what Zabbix does (modelled in `hwh/expr.py::run_trigger`)?
3. **Fail-closed isolation** (`labsim.may_match`): look for an action shape that matches events but is judged not to.
4. **Definitions vs sources**: A8 of the checklist.
5. `tplmgr` ownership: try a template whose description contains the marker but was created by an operator.

## Honest status
IMPLEMENTED + SIMULATED TESTED for 5 definitions (11 cells); 0 REAL DEVICE VERIFIED; Telegram NOT TESTED; action disabled; Production untouched. Verdict: **RELEASE CANDIDATE READY for LAB acceptance, not production-ready.**

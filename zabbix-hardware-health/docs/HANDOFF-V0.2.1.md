# Claude -> Codex: Hardware Health v0.2.1 (source-only corrections)

Branch `claude/hardware-health-v0.2.1`, based on your acceptance commit `41f12c3`. The candidate SHA is given in the final report and is the commit that introduces this file.

Corrections: see AUDIT-CORRECTIONS.md items 12-16. No live system was touched; nothing was written to LAB or Production; the action remains disabled; both approved inventories are `hosts: {}`; Interface Alerting v1.0.2 is byte-identical.

## Verify (offline, Python 3.12 + the declared dependency)

```bash
cd zabbix-hardware-health
python3.12 -m venv /tmp/hwvenv && /tmp/hwvenv/bin/pip install -r requirements.txt
/tmp/hwvenv/bin/python -W error::ResourceWarning -m unittest discover -s tests -t .      # expect 125 tests OK
git diff --quiet v1.0.2 HEAD -- ../zabbix-alerting && echo "Interface Alerting identical to v1.0.2"
```

## Live checks that remain yours

1. `discover --host PNET-SITE-A`: `raw_input_count` = all raw inputs (12 on SITE-A), `environmental_raw_input_count` = 3, `candidate_sensor_count` = 0.
2. `action plan` with an operator-approved `config/notifications.lab.yaml` (the shipped example is refused by design).
3. The quoted `{EVENT.TAGS."..."}` macros only prove themselves in a delivered message: use SYNTHETIC-NOTIFICATION-TEST.md. **It needs explicit approval first; nothing in this branch runs it.**

## Still blocked
Real devices for the four vendors; verified vendor status mappings; the trigger-tagging mechanism; approved LAB recipients; delivery validation.

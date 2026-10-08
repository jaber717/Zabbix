# Release v1.0.1 - Zabbix Interface Alerting-as-Code

Supersedes v1.0.0 (tagged earlier the same day before the operator-usability review; **install v1.0.1, not v1.0.0**).

> **Superseded by v1.0.2.** This release (v1.0.1, tag unchanged) failed final release acceptance only because `scripts/ingest-handover.py` did not compile (unterminated string). All live LAB checks passed. Install v1.0.2 - see `RELEASE-v1.0.2.md`.

* Operator guide: `OPERATOR-GUIDE.md`. Production runbook: `docs/PRODUCTION-INSTALL.md`. Design/validation: `docs/DESIGN.md`.
* Per-environment inventories and notification settings (Telegram in LAB, SMTP e-mail in Production by configuration only).
* Safety: environment identity gate, ownership markers, backups, `--confirm production`, VERIFICATION INCOMPLETE blocks applies.
* Install/upgrade commands were rehearsed from a real GitHub clone (clone, local `prod-local` branch, release merge, conflict case,
  startup behaviour on a Linux host, offline tests on the configured tree).
* Known limits: SNMP traps (Phase 2); stock trigger suppression off; rollback, e-mail delivery and production not yet exercised on a real
  Zabbix; post-LAB changes need the Codex LAB re-run. LAB Telegram bot is temporary and must be revoked at decommissioning.

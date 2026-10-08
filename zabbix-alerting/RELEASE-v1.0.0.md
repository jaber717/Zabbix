# Release v1.0.0 - Zabbix Interface Alerting-as-Code

* Install from GitHub: `docs/PRODUCTION-INSTALL.md`. Operator guide: `README.md`. Design and validation: `docs/DESIGN.md`.
* Per-environment inventories: `config/interfaces.lab.yaml` (18 verified LAB P2P links), `config/interfaces.production.yaml` (empty).
* Safety: environment identity gate, ownership markers, backups, `--confirm production`, VERIFICATION INCOMPLETE blocks applies.
* Known limits: SNMP traps (Phase 2); stock trigger suppression is off by default; rollback and the post-LAB changes are
  validated offline only; production has not been exercised. LAB Telegram bot is temporary and must be revoked at decommissioning.

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

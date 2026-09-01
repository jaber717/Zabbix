# M4 Permission-Blocker Resumption Start

Date: 2026-09-01

- Branch: `main`
- Authoritative blocked handover commit:
  `54df4e87fb10683e2dddce6313680754b0c55947`
- Existing M4 implementation/evidence commit:
  `936a3ef3b1cb81fa1016eebb44f080c674426f81`
- Starting worktree: clean
- Claimed operator action: grant only
  `virtualization.view_virtualmachine`,
  `virtualization.view_vminterface`, `extras.view_tag`, and
  `extras.view_customfield` to the existing integration account.

This resumption will revalidate the exact GET-only endpoints before any other
gate. NetBox writes, permission changes, change-budget overrides, Zabbix apply,
M5, M6, and external push remain outside scope unless every existing M4 runtime
gate passes.

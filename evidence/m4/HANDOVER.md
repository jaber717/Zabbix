# M4 Final Handover

1. **NetBox preflight/version:** API reachable and authenticated; NetBox 4.6.9,
   API 4.6, Django 6.0.8. The earlier 6.0.8 inference was a Django-version
   misclassification and is corrected.
2. **API permission matrix:** devices, DCIM interfaces, IP addresses, roles,
   platforms, sites, and tenants pass; VMs, VM interfaces, tags, and custom
   fields return 403.
3. **Architecture:** LXC 9000 / `192.168.1.89` GET-only NetBox API to sync on
   Zabbix `192.168.1.91`, then Zabbix JSON-RPC. The pre-existing NetBox software
   on the Zabbix host is not used as source.
4. **Components:** standard-library Python package, runtime config, explicit
   mappings, 29-test fixture suite, Ansible role, systemd service/timer, runbook,
   and evidence.
5. **Identity:** `source=netbox`, `netbox_type=device|vm`, `netbox_id=<pk>`.
6. **Mapping:** Git-managed JSON/YAML-1.2 configuration with per-dimension
   `RESOLVED`, `UNMAPPED`, `AMBIGUOUS`, and `NEEDS_REVIEW` states.
7. **Eligibility:** explicit `monitoring-enabled` tag or boolean
   `monitoring_enabled` custom field; denied metadata becomes UNKNOWN.
8. **Management IP:** primary IPv4 then IPv6 only, verified against readable IP
   inventory; invalid/special/missing/duplicate values fail closed. Existing IP
   change is report-only.
9. **Dry-run:** immutable default; installed unit has no `--apply` flag and
   returns structured aggregate JSON.
10. **Change budget:** configurable 10%; plan computes modifications divided by
    managed/actionable population and blocks excess without explicit override.
11. **Destructive safeguards:** no host delete, template unlink, group removal,
    or IP-change apply path; template/group removals and orphans report only.
12. **Secrets:** two root:root 0600 systemd host-encrypted credentials; values are
    absent from Git, unit arguments, normal logs, and evidence.
13. **Tests:** 29 Python 3.9 tests pass; 17 M2 regressions, Bash syntax, installer
    manifest, role idempotence, and systemd verification pass.
14. **Actual dry-run:** 81 devices, 1105 DCIM interfaces, and 116 IPs read; VM,
    VM-interface, tag, and custom-field counts remain UNKNOWN; 0 creates and 0
    updates proposed.
15. **Actual apply:** NOT-EXECUTED because required-read, candidate-resolution,
    and scoped-credential gates are blocked.
16. **Second reconciliation:** NOT-EXECUTED because no apply occurred. Two
    blocked dry-runs were byte-identical, proving only deterministic planning.
17. **systemd:** dedicated `nbzsync` nologin account; hardened one-shot service;
    enabled active timer at approximately ten-minute intervals. The service
    deliberately exits 3 while blocked.
18. **Zabbix before/after:** one total/enabled host, zero NetBox-managed hosts,
    12 unsupported enabled items, two queue items at zero, core services active,
    and no boot-scoped Zabbix Server errors before and after.
19. **Unsupported/unmapped:** 57 readable device records are unmapped, 24 have
    resolved mappings, and all 81 have UNKNOWN eligibility. These are plan facts,
    not approved monitoring decisions.
20. **Permission blockers:** minimum NetBox views are
    `virtualization.view_virtualmachine`, `virtualization.view_vminterface`,
    `extras.view_tag`, and `extras.view_customfield`.
21. **Compatibility:** running NetBox and portal health agree on 4.6.9; API 4.6
    works with feature-detected collection shapes. Django is 6.0.8. Portal M6
    work was not started.
22. **Safety:** NetBox received GET/HEAD only; no NetBox user/permission/token,
    object, schema, service, firewall, SELinux, network, Proxmox, or other guest
    change occurred.
23. **Documentation/evidence:** operations runbook plus preflight, tests,
    dry-run, blocked apply, blocker, audit, handover, raw transcripts, and
    checksums under `evidence/m4/`.
24. **Git:** M4 start commit `e389a51`; implementation/evidence commit
    `936a3ef3b1cb81fa1016eebb44f080c674426f81`; final handover is committed
    separately. Nothing is pushed externally.
25. **Remaining blockers:** exact NetBox reads above, then a dedicated minimally
    scoped Zabbix apply credential, mapping review for any eligible unmapped
    objects, safe dry-run review, apply, and post-apply second reconcile.
26. **M5 verdict:** **NOT READY**. Final M4 verdict is
    **M4 BLOCKED — NETBOX READ PERMISSIONS**. Stop after M4.

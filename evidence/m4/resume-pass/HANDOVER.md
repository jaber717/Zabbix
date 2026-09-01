# M4 Final Handover

1. The existing `topology-portal` credential now receives HTTP 200 for virtual
   machines, VM interfaces, tags, and custom fields.
2. All required NetBox datasets are readable from `http://192.168.1.89`.
3. Actual inventory is 81 devices, 0 VMs, 0 VM interfaces, 0 tags, and 1 custom
   field.
4. All 81 devices are ineligible because none is opted in through the approved
   tag or custom field; the individual reason ledger is preserved.
5. Mapping is 24 resolved and 57 unmapped; 41 candidates lack a primary IP;
   no identity or IP duplicate exists. These records are ineligible and no
   unsafe inference was made.
6. The plan proposed 0 creates and 0 updates, a 0.0 ratio against the 0.1 limit.
7. Dedicated Zabbix user `nbzsync` has an API allow-list, no frontend, only two
   mapped host groups read-write, and only two template groups read-only.
8. Host deletion, template removal, and user enumeration are denied to that
   identity.
9. Explicit apply passed with 0 creates/updates. Second reconciliation passed
   with 0 creates/updates.
10. The approximately ten-minute timer remains enabled and waiting; an actual
    scheduled trigger exited 0 with every gate passing and zero changes. Its
    service defaults to dry-run and contains no `--apply` flag.
11. NetBox's recent 1,000-request audit from Zabbix contains GET only.
12. Zabbix health is unchanged: one enabled host, zero NetBox-managed hosts, 12
    unsupported enabled items, zero queues, active core services, no server
    errors this boot.
13. Twenty-nine target tests, systemd verification, runtime static safety, raw
    checksums, secret scan, whitespace validation, and Git review pass.
14. Historical blocked evidence is preserved. M5 was not started and nothing
    was pushed externally.
15. M4 acceptance implementation/evidence commit:
    `30a48094928ba3ec97db6529cf90d9f065d7767e`.

Final verdict: **M4 ACCEPTED — M5 READY**. Stop after M4.

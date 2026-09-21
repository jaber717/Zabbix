# Availability v1 live validation

Date: 2026-09-22

## Result

Availability v1 is installed and enabled in the lab Zabbix frontend as module
ID 31. The authenticated widget action renders successfully. This validates the
lab integration only; it does not define production Nodes or validate real
device reachability.

## Verified target

- Host: `netbox-dev` / logical `ZABBIX-01`, `192.168.1.91`
- OS: Red Hat Enterprise Linux 9.6, x86-64
- Zabbix: 7.0.30
- PHP: 8.3.19
- Frontend root: `/usr/share/zabbix`
- External module root: `/usr/share/zabbix/modules`
- HTTPS: port 8443, HTTP 200, certificate verification PASS
- `zabbix-server`, `php-fpm`, and `nginx`: active

## Differences found before correction

1. The dedicated `nbzsync` API role can call `host.get` but intentionally
   cannot call `item.get`, `history.get`, `trigger.get`, or `problem.get`.
   Full compatibility was therefore checked with a protected administrator
   maintenance context; the sync role was not changed.
2. Zabbix's module autoloader lowercases nested namespace directories. The
   offline Windows implementation used uppercase `Collector`, `Config`, and
   `Domain` directories, which failed on RHEL's case-sensitive filesystem.
   They were renamed to `collector`, `config`, and `domain`; no namespace,
   state, query, or presentation behavior changed.
3. Live item storage normalizes latest history outside the `items` table, but
   the installed 7.0.30 `CItem` API explicitly supplies the requested
   `lastclock` and `lastvalue` fields. No collector redesign was required.

## Live API and data

Authenticated compatibility passed for `host.get`, `item.get`, `history.get`,
`trigger.get`, `problem.get`, and `module.get`.

- Monitored Hosts: 5
- Selected availability items: 9
- Five-minute availability history rows: 46
- Active triggers/problems: 6 / 6
- Trigger dependency edges present in the database: 1923
- Host classification tags currently present: `source`, `netbox_type`, and
  `netbox_id` on the four NetBox mock devices
- `site`, `criticality`, and `availability_source_id` tags: absent
- Central Node definitions: intentionally empty

## Render validation

- First and second widget requests: HTTP 200
- Observed request times: 104.445 ms and 106.714 ms
- Internal instrumentation: 5 API calls; collector 33.473 ms; resolver
  0.733 ms; total widget execution 34.902 ms
- Objects retrieved/resolved: 5 Hosts, 5 members, 5 Nodes, 6 Problems
- Rendered Node cards / Sites / secondary incidents: 5 / 1 / 3
- Summary: 1 UP, 4 DOWN, 0 DEGRADED, 0 UNKNOWN, 0 visibility loss,
  0 maintenance, 1 impacted Site
- Hero continuity across the second request: PASS
- Visible `UNCLASSIFIED` and `Configuration required`: PASS
- Warning/error state: absent
- Recent PHP/nginx warnings and relevant SELinux AVCs: none
- Browser-console inspection: NOT-EXECUTED because the local browser-control
  runtime could not initialize (`os error 3`); no browser-console result is
  inferred from the server-side checks

Brief real-data checks matched the widget result:

- `ZABBIX-01`: native `agent.ping=1` (one-minute interval, fresh value); widget
  state UP with full visibility
- `DR-FW01`: native `icmpping=0` and SNMP unavailable (fresh one-minute
  availability input); widget state DOWN with full visibility
- `DR-LB01`: native SNMP availability is 0 (fresh one-minute input); widget
  state DOWN with full visibility

Because no central Node definitions or `site`/`criticality` tags exist, all
five cards remain visibly `UNCLASSIFIED / Configuration required`. The
resolver's internal single-member safety fallback is not asserted as a
production Node policy or production criticality classification.

The four DOWN objects are the existing mock NetBox devices with intentionally
fake/non-routable management addresses. Their state is expected lab input and
is not classified as a module, credential, template, or routing defect.

## Installation state

- Path: `/usr/share/zabbix/modules/NetworkAvailability`
- Owner/mode: root:root, directories 0755, files 0644
- SELinux label: `system_u:object_r:usr_t:s0`
- Workspace/VM SHA256 parity: PASS
- Official manifest validation and class initialization: PASS
- Module record: ID 31, enabled, empty config
- Service restart: not required and not performed

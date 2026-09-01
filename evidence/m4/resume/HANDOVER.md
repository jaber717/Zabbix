# M4 Permission-Resumption Handover

Final verdict: **M4 BLOCKED — NETBOX READ PERMISSIONS**.

The reported four-permission grant was revalidated against the credential used
by the installed `nbzsync` service. Devices, DCIM interfaces, IP addresses,
roles, platforms, sites, and tenants still pass. Virtual machines, VM
interfaces, tags, and custom fields still return HTTP 403.

The resulting dry-run classified all 81 readable device eligibility decisions
as `UNKNOWN`, left VM and orphan counts unknown, and proposed zero creates and
zero updates. Its 0.0 change ratio is within the 0.1 budget, but source
completeness and candidate resolution are blocked. No least-privilege Zabbix
credential was created, no apply ran, and no second reconciliation ran.

The installed safety controls and 29 tests pass. Zabbix remains healthy with
one enabled host, zero NetBox-managed hosts, 12 unsupported enabled items, zero
queue values, active core services, and no boot-scoped Zabbix Server error.

Minimum next action: make the four exact view permissions effective for the
actual NetBox principal/token used by `nbzsync`, including intended-object scope,
then rerun the bounded read-only preflight. Do not grant broader NetBox access.
M5 remains not ready.

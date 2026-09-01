# M4 BLOCKED — NETBOX READ PERMISSIONS

M4 is not accepted and M5 is not ready.

The existing NetBox credential returns HTTP 403 for:

- `/api/virtualization/virtual-machines/`
- `/api/virtualization/interfaces/`
- `/api/extras/tags/`
- `/api/extras/custom-fields/`

Minimum operator action: add only the `view` actions corresponding to
`virtualization.view_virtualmachine`, `virtualization.view_vminterface`,
`extras.view_tag`, and `extras.view_customfield` to the existing credential
user's constrained NetBox object permissions. Do not grant add/change/delete,
administrator, or unrestricted global permissions.

After that permission change, provision a dedicated minimally scoped Zabbix
service credential to replace the current discovery-only Admin credential.
Then resume M4 at the API preflight and real dry-run. No redesign or rebuild of
the integration engine is required.

Do not start M5 until a safe apply and post-apply second reconciliation pass.

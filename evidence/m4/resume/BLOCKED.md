# M4 BLOCKED — NETBOX READ PERMISSIONS

M4 is not accepted and M5 is not ready.

After the reported permission grant, the installed integration credential still
receives HTTP 403 for:

- `/api/virtualization/virtual-machines/`
- `/api/virtualization/interfaces/`
- `/api/extras/tags/`
- `/api/extras/custom-fields/`

The exact remaining operator requirement is to make only
`virtualization.view_virtualmachine`, `virtualization.view_vminterface`,
`extras.view_tag`, and `extras.view_customfield` effective for the NetBox
principal actually represented by the credential used by `nbzsync`, including
any constrained object-permission scope needed for the intended objects. Do not
grant NetBox add, change, delete, administrator, or unrestricted global access.

After correction, revalidate the same four GET endpoints. Only if every required
source read passes may M4 proceed to the separate dedicated least-privilege
Zabbix credential gate, a fresh dry-run, reviewed apply, and second
reconciliation.

The scoped Zabbix credential was not created or tested during this resumption,
because incomplete NetBox source data triggered the required early stop. Apply
and second reconciliation are `NOT-EXECUTED`. No M5 work began.

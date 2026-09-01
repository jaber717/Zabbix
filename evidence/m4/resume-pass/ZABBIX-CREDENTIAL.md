# M4 Zabbix Least-Privilege Credential

The unattended runtime now authenticates as Zabbix user `nbzsync` through a
root-owned mode 0600 systemd host-encrypted password. No password or API token
was written to Git, configuration, evidence, process arguments, or normal logs.

## Effective scope

- Role: `NetBox Sync API`, type Admin as required for host configuration.
- Frontend access: disabled.
- UI, module, and action default access: disabled.
- API mode: allow-list only.
- Allowed methods: `host.get`, `hostgroup.get`, `template.get`, `host.create`,
  `host.update`, and `template.massadd`.
- Host-group rights: read-write only to `Discovered hosts` and
  `Virtual machines`.
- Template-group rights: read-only only to `Templates/Network devices` and
  `Templates/Operating systems`.

Live negative checks confirmed `host.delete`, `template.massremove`, and
`user.get` are denied. Required groups and mapped templates are visible. The
former encrypted Admin credential is retired from the service path and retained
root-only as a rollback artifact; it is not loaded by `nbzsync`.

Raw evidence: `raw/zabbix-least-privilege.txt` and `raw/runtime-safety.txt`.

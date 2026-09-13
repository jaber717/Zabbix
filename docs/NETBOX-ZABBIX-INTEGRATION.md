# Optional NetBox to Zabbix integration

The retained `integrations/netbox-zabbix-sync` code is the sanitized reusable
standard-library reconciler discovered on the source host. NetBox is read-only
by construction (`GET`/`HEAD` only); Zabbix changes are explicit creates and
additive updates. Deletes, template removals, and automatic IP replacement are
report-only. Stable identity uses `source=netbox`, object type, and NetBox ID.

Fresh deployment leaves both `nbzsync_enabled` and `nbzsync_timer_enabled`
false. Zabbix works without NetBox.

Before enabling it:

1. Copy and review `config/runtime.json` and `config/mappings.json`; replace all
   `.example.invalid` names and example mappings.
2. Create a dedicated NetBox token with only the required view permissions and
   a dedicated least-privilege Zabbix API account.
3. Store values with systemd encrypted credentials named `netbox-token` and
   `zabbix-password`; never write them to JSON or Git.
4. Install trusted NetBox/Zabbix CA certificates.
5. Ensure every referenced host group/template already exists.
6. Run tests and a dry-run, inspect the report, then explicitly authorize apply.
7. Set `nbzsync_enabled=true` only in protected installer variables and enable
   the timer separately after successful dry-runs.

SNMP mappings create an SNMPv3 authPriv interface referencing credential macros;
the operator must supply host macro values securely. The normal 10% change
budget remains fail-closed. To disable, stop and disable the timer; this does not
delete Zabbix hosts or write to NetBox.

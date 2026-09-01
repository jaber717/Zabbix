# NetBox to Zabbix Sync Operations

## Architecture and status

`netbox-zabbix-sync` runs on logical `ZABBIX-01` (`192.168.1.91`) and reads the
authoritative NetBox API in LXC 9000 (`192.168.1.89`). NetBox is intended state;
Zabbix is operational state. The service never writes to NetBox.

The lab NetBox listener exposes HTTP on port 80 and no listener on port 443. The
lab configuration therefore contains an explicit environment-only HTTP
exception. Zabbix API traffic uses HTTPS 8443 with the installed lab public
certificate. Corporate configuration must replace endpoints, mappings,
credentials, and certificates without changing Python source.

M4 is accepted as of 2026-09-02. The existing NetBox credential for principal
`topology-portal` returns HTTP 200 for virtual machines, VM interfaces, tags,
and custom-field metadata as well as every previously working collection. The
installed timer service remains dry-run by default and exits successfully when
all gates pass.

On 2026-09-01, a bounded resumption revalidated an operator-reported grant of
the four exact view permissions. The credential used by the installed service
still received the same four HTTP 403 responses; already-readable endpoints
continued to pass. This proves only that the views are not effective for the
credential actually presented. It does not identify whether principal
attachment, object constraints, or another permission rule is responsible.
That failed resumption remains historical evidence. A later operator correction
made all four views effective; the successful validation and closeout are under
`evidence/m4/resume-pass/`.

## Components

- `/usr/libexec/netbox-zabbix-sync/netbox_zabbix_sync/`: Python 3.9-compatible,
  standard-library-only client, resolver, planner, and CLI.
- `/etc/netbox-zabbix-sync/runtime.json`: endpoints and safety policy; no secret.
- `/etc/netbox-zabbix-sync/mappings.json`: reviewed lab mappings; no secret.
- `/var/lib/netbox-zabbix-sync/last-report.json`: aggregate machine-readable
  result with no object records or credentials.
- `netbox-zabbix-sync.service`: hardened one-shot unit running as `nbzsync`.
- `netbox-zabbix-sync.timer`: persistent approximately ten-minute schedule.

Git-managed mapping files use JSON, which is a YAML 1.2 subset, so the runtime
needs no third-party YAML package. Mapping logic is not embedded in Python.

## Required NetBox permissions

The credential needs only view access for data consumed by Phase 1. These four
minimum Django/NetBox view permissions are now effective:

- `virtualization.view_virtualmachine`
- `virtualization.view_vminterface`
- `extras.view_tag`
- `extras.view_customfield`

Do not add change, delete, or sync actions. Existing view access for devices,
DCIM interfaces, IP addresses, roles, platforms, sites, and tenants passes and
should not be broadened.

## Identity and eligibility

Every managed Zabbix host uses this stable tag tuple:

```text
source=netbox
netbox_type=device|vm
netbox_id=<NetBox primary key>
```

Hostname, display name, and IP address are mutable attributes, not primary
identity. Devices and virtual machines have separate identity namespaces even
when their integer primary keys match.

Eligibility is explicit: the lab mapping recognizes tag `monitoring-enabled` or
boolean custom field `monitoring_enabled`. If tag or custom-field metadata is
denied, eligibility is `NEEDS_REVIEW`; it is never inferred true or false.
Objects that do not opt in after both datasets are readable are ineligible.

## Mapping and IP resolution

The resolver evaluates object type, role, platform, and site independently. Its
states are `RESOLVED`, `UNMAPPED`, `AMBIGUOUS`, and `NEEDS_REVIEW`. An eligible
object with any unresolved required dimension blocks apply.

Management IP resolution uses only NetBox `primary_ip4`, then `primary_ip6`. The
selected primary IP ID must exist in the readable IP-address collection. The
engine rejects invalid, loopback, link-local, multicast, unspecified, missing,
and duplicate addresses. It never selects the first interface address. An
existing Zabbix management-IP difference is report-only in M4 because identity
confirmation is not sufficient for a blind switch.

## Planning, apply, and safety gates

Running the command without `--apply` always produces a plan. Apply additionally
requires all required NetBox reads, deterministic candidate resolution, unique
stable identities, available Zabbix mapping targets, an approved scoped Zabbix
credential, and a modification ratio at or below 10 percent. An explicit
`--override-change-budget` is required to exceed the budget and does not bypass
any other gate.

Allowed apply paths are Zabbix host create, safe metadata/tag/group additions,
and template additions. Template additions use `template.massadd`, avoiding
replacement semantics. Existing group and template removals, IP changes, and
orphans are report-only. There is no automatic host deletion, template unlink,
group removal, or management-IP mutation path.

The runtime now uses dedicated Zabbix user `nbzsync`. Its Admin-type role is
restricted to the six API methods required by the implementation, has no
frontend/UI/module/action access, has read-write access only to `Discovered
hosts` and `Virtual machines`, and read-only access only to the required network
and operating-system template groups. `host.delete`, `template.massremove`, and
`user.get` are denied. The regular timer remains dry-run; explicit apply still
requires the command-line flag and every runtime gate.

## Credentials

The service consumes:

```text
/etc/credstore.encrypted/nbzsync-netbox-token
/etc/credstore.encrypted/nbzsync-zabbix-password
```

Both files are root-owned mode 0600 systemd host-encrypted credentials. systemd
materializes them only in the service credential directory. Values must never
appear in Git, configuration, unit arguments, journal output, or evidence. The
authoritative recovery and rotation copy remains operator-owned.

## Operation and troubleshooting

Read current aggregate state:

```bash
sudo systemctl status netbox-zabbix-sync.timer
sudo journalctl -u netbox-zabbix-sync.service --since today
sudo sed -n '1,240p' /var/lib/netbox-zabbix-sync/last-report.json
```

Trigger a dry-run only:

```bash
sudo systemctl reset-failed netbox-zabbix-sync.service
sudo systemctl start netbox-zabbix-sync.service
```

Exit 0 with all gates `PASS` is the expected current state. Exit 3 indicates a
blocked planning gate, and exit 2 is a fail-safe runtime/configuration/API
failure. Check endpoint status,
certificate validity, credential rotation, mapping validation, and duplicate
identity/IP gates; never work around failure by widening NetBox write access.

## Rollback and manual remediation

Stopping or disabling the timer prevents future plans and does not alter either
system. The former Admin credential remains encrypted, root-only, and retired
outside the loaded credential path for controlled rollback. Do not restore it
to unattended use; use it only for an approved recovery action. Preserve the
last reports and credential ownership records.

If a later authorized apply creates or updates an incorrect host, disable the
timer first, retain the report, and remediate Zabbix manually by stable NetBox
identity. Do not delete or edit NetBox data to force reconciliation. Template
unlink, host deletion, and IP changes require separate explicit operator review.

## Known limitations

- Current NetBox HTTP transport is a lab exception; the LXC has no HTTPS
  listener. A production design requires protected transport.
- The current NetBox source has no virtual machines or eligibility tag and no
  truthy `monitoring_enabled` values, so there are presently no opted-in hosts.
- Fifty-seven ineligible records are unmapped and 41 lack a primary IP. These
  remain visible plan facts; either condition fails closed if a record is later
  opted in.
- SNMP credentials and optional reachability/sysName confirmation are not part
  of M4; IP changes remain report-only.
- The accepted live apply was a zero-change reconciliation because no source
  object is opted in; it does not claim a host-create mutation was exercised.

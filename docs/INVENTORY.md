# Release inventory

Historical source-host paths and internal hostnames have been removed from this
publication inventory. They are not production prerequisites.

| Tracked source | Purpose | Runtime dependency |
|---|---|---|
| `install.sh`, `verify.sh`, `scripts/` | Protected entry points and staging | Operator runtime file outside Git |
| `installer/` | Bootstrap, shared controls, roles, templates, manifest | Generated local bundle; root privileges |
| `build/` | Isolated collection, signatures, module metadata, closure tests | Authorized RHEL and official Zabbix repositories |
| `compat/zabbix-7.0.yaml` | Application/source policy and supported family | Generated bundle records concrete target minor |
| `manifests/rpm-lockfile.txt` | Historical 313-RPM immutable lock | Explicit frozen build comparison only |
| `integrations/netbox-zabbix-sync/` | Generic optional integration, disabled by default | Operator endpoints/credentials if enabled separately |
| `tests/` | Installer, portability and reconciler regression tests | Python and Bash; no production secrets |

Generated RPMs, bundle trees, raw logs, environment files, credentials and
backups remain outside Git. The historical accepted bundle had 313 RPMs:
167 BaseOS, 132 AppStream, 13 official Zabbix, and one fping from the narrowly
approved non-supported repository. Future CONNECTED builds resolve OS
dependencies from their own authorized repository content; 313 is not an
acceptance requirement for those builds.

Production generates its package tree, manifests, runtime directories,
PostgreSQL schema, service configuration and host encryption key. It does not
copy these from a previous lab deployment. DNS, routing, entitlement,
proxy/CA configuration and deployment secrets are operator prerequisites.

See PRODUCTION-READINESS.md for current validation limits. Earlier clean-host
qualification in TEST-EVIDENCE.md does not qualify current changes on a fresh
host or on RHEL 9.7.

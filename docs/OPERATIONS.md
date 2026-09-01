# Configuration, Verification, and Troubleshooting

## Environment variables

The canonical defaults are in `installer/inventory/group_vars/all.yml` and an
RFC 5737-only example is in `installer/examples/installer-vars.yml`.

Required environment values are:

- `zabbix_server_hostname` and `zabbix_web_server_name`.
- `zabbix_firewall_web_sources`, `zabbix_firewall_server_sources`, and
  `zabbix_firewall_agent_sources`; every list must contain explicit CIDRs.
- `zabbix_tls_certificate_source` and `zabbix_tls_private_key_source` when
  `zabbix_tls_enabled` is true.

Phase 1 uses local PostgreSQL with `zabbix_db_mode: local` and
`zabbix_db_manage: true`. A future external database uses
`zabbix_db_mode: external`, `zabbix_db_manage: false`, and parameterized host,
port, TLS, name, and user values; the installer will not administer a remote
database.

The server listen address/port, Agent 2 allowed/active peers, web ports, backup
schedule/root, and conservative Zabbix cache sizes are configurable. Tune cache
sizes only from measured load.

## Secrets and TLS

The database password enters through `ZABBIX_DB_PASSWORD_FILE`, is read with
Ansible `no_log`, and is encrypted into
`/etc/credstore.encrypted/zabbix-db-password` using `systemd-creds`. Zabbix
Server and PHP-FPM receive the encrypted credential through systemd and render
root-owned runtime files under `/run`; the committed Zabbix and PHP
configuration contains no plaintext password.

TLS is enabled by default. The installer validates certificate lifetime,
hostname, private-key structure, and certificate/key public-key match before
installing the inputs. It does not create a private CA or fabricate corporate
trust. Rotate database and TLS secrets only under a separately reviewed
operational change with a backup; M2 automates initial protected injection, not
unattended secret rotation.

## Verification

`installer/playbooks/verify.yml` checks:

- required installed NEVRAs are present in the immutable M1 lock;
- PostgreSQL 16, PHP 8.3, and nginx 1.24 module streams are enabled;
- PostgreSQL, Zabbix Server, Agent 2, PHP-FPM, nginx, and firewalld are enabled
  and active;
- the `dbversion` schema marker and database connectivity;
- nginx and Agent 2 configuration validity;
- the local HTTP or HTTPS frontend response;
- expected TCP listeners using `/proc/net/tcp*` without an extra package;
- SELinux Enforcing and firewalld running; and
- a `file://` repository definition and a local-only DNF probe.

The site playbook runs verification at the end unless
`m2_run_verification: false` is explicitly set for diagnosis. Re-enable it
before acceptance.

## Troubleshooting

- **Checksum failure:** stop; compare the transferred release and installer to
  their accepted hashes. Do not regenerate a manifest around damaged inputs.
- **Package not found:** confirm the M1 repository path and metadata. Do not
  enable CDN, EPEL, an online Zabbix repository, or the pre-existing NetBox
  repositories.
- **Target rejected:** require exact RHEL 9.6 x86_64 and SELinux Enforcing; do
  not weaken the check.
- **Existing release rejected:** use the upgrade preflight for a forward change.
  Downgrade is unsupported.
- **Database object already exists:** the role probes role, database, and schema
  markers and converges safely. A credential mismatch is an operator-controlled
  rotation problem, not permission to drop or recreate the database.
- **nginx/PHP failure:** use `nginx -t`, `php-fpm -t`, and `journalctl` for the
  named services. Apache is intentionally stopped and masked.
- **SELinux denial:** preserve Enforcing, capture the actual AVC, and review the
  vendor policy. Do not add guessed booleans or broad custom policy.
- **Firewall failure:** validate each CIDR and inspect permanent rich rules in
  the configured zone. Empty source lists are intentionally refused.

## M2 test boundary

Static validation, helper unit tests, shell/Python syntax checks, offline
`ansible-core` resolution, and Ansible playbook syntax are M2 gates. Full
service operation, first converge, second-run idempotency, converged-target
check mode, reboot, SELinux AVC behavior, firewalld reachability, frontend/API,
and database restore require the dedicated M3 VM and are `NOT-EXECUTED` in M2.

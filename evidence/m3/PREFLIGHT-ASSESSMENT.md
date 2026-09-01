# M3 Preflight Assessment

Date: 2026-09-01

Target: `192.168.1.91` (`netbox-dev`)

## Gate results

| Gate | Status | Observed result |
|---|---|---|
| RHEL release / architecture | PASS | RHEL 9.6, x86_64 |
| SELinux | PASS | Enforcing |
| Capacity | PASS | 4 CPUs, 11 GiB RAM, 46 GiB free on `/`, 21 GiB free on `/home` |
| firewalld | PASS | Active; public zone on `ens18` |
| PostgreSQL safety | PASS | PostgreSQL 16.10 is active and contains a meaningful `netbox` database with 198 user tables. Passing required the documented coexistence controls: it must not be initialized, replaced, or interrupted. |
| Web coexistence | PASS | nginx serves NetBox on 80/443. Passing required Zabbix to use HTTPS 8443 and no HTTP redirect. |
| Zabbix pre-existence | PASS | No Zabbix RPM or service exists; ports 10050/10051 are unused. |
| Unrelated workloads | PASS | NetBox, NetBox RQ, nginx, PostgreSQL, Redis, and firewalld are running; passing required them to remain available. |

## Required bounded corrections before converge

The accepted M2 role would have replaced the whole `pg_hba.conf` and restarted
shared PostgreSQL/nginx services. That is unsuitable for this newly authorized
dual-purpose host, although it was not exercised in M2.

Before M3 converge the role is amended to:

- use an Ansible managed block for only the Zabbix database/user access rules,
  preserving every pre-existing PostgreSQL authentication rule;
- reload PostgreSQL for reloadable authentication/password-encryption changes,
  retaining restart only for an actual listen-address change;
- reload nginx after validated configuration/TLS changes rather than restart it;
- use M3-only HTTPS port 8443 with an explicit `192.168.1.0/24` source CIDR and
  no port-80 redirect, preserving NetBox on 80/443.

The Zabbix role will create only a separate `zabbix` role/database/schema after
absence probes. It will not initialize the existing cluster because
`/var/lib/pgsql/data/PG_VERSION` exists.

Verdict: **PASS** — safe coexistence is supportable with these bounded controls;
convergence may proceed only after their static/syntax validation and installer
manifest regeneration.

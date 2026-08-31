# SPEC-02 — Installer

## Responsibilities

Small Bash bootstrap code may verify the artifact, run basic preflight, configure
the local DNF repository, bootstrap ansible-core, and hand off. Ansible owns
idempotent system configuration. Do not create a monolithic Bash installer.

## Required configuration

Configure PostgreSQL, Zabbix server and frontend, nginx, PHP-FPM, TLS, Zabbix
Agent 2, SELinux, firewalld, systemd units/timers, logs, and backup/restore paths.
Use only artifact-contained packages and wheels on a disconnected target.

## State and database safety

Persist release state in `/etc/zabbix-offline/release.json` with enough data to
distinguish fresh install, same-release convergence, upgrade, and unsupported
downgrade. Normal install must not reinitialize, drop, overwrite, or downgrade an
existing database. Destructive recovery is a separately authorized procedure.

## Idempotency and check mode

Repeated installation must converge safely. On a converged host, Ansible check
mode must report zero unexpected changed tasks. Tasks that cannot support check
mode must be isolated and documented; do not hide failures with broad
`ignore_errors: true`.

## Security and networking

- Keep SELinux Enforcing; add only evidenced, versioned policy source.
- Keep firewalld enabled and expose only documented flows.
- Require approved TLS certificates and validate identity, chain, permissions,
  and expiry. Do not silently generate production trust.
- Use least-privilege service accounts and runtime secret stores. Never place
  secrets in Git or ordinary committed variables.

## Lifecycle

Document and test fresh install, converge, backup, restore, upgrade, rollback
limits, and failure recovery. Major version/schema transitions are major releases.
Rollback must state when database restore is required and must never imply an
unsafe in-place downgrade.

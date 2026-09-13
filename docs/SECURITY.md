# Security

## Credentials

The repository contains placeholders only. `.env.example` deliberately has no
values. Store deployment input at `/root/zabbix-install.env`, owned by root and
mode 0600 (0400 is also accepted). The parser treats values as inert data and
does no shell expansion, so special characters are preserved.

During installation, secret copies exist only in a mode-0600 directory under
`/run` and are removed on exit. Ansible uses `no_log` on secret-bearing tasks.
Both installer entry points pass the protected runtime configuration to the
repository scanner. It compares the deployment password in memory against every
release file and fails closed on an unreadable/invalid input or an exact match;
the password is never printed, hashed, or placed directly in command arguments.
The DB credential is encrypted using the host systemd credential key. The Admin
password is converted to bcrypt using PHP's current password API and is passed
to PostgreSQL on standard input. Direct DB initialization is used because a
fresh application has no safe pre-existing API credential; successful API login
with the configured password and rejection of the factory credential are then
mandatory checks.

## Host controls

- SELinux must start and remain Enforcing.
- The vendor `zabbix-selinux-policy` package is mandatory.
- Only documented supported booleans are changed; no generated broad policy is
  installed.
- Firewalld source CIDRs fail closed and only TCP frontend, 10051, and 10050 are
  managed. SNMP traps and UDP/162 are out of scope.
- TLS keys must be root-owned 0400/0600 and match the certificate.
- Recent relevant AVCs and fatal server journal messages fail verification.

## SNMP

Use SNMPv3 authPriv with SHA-256 and AES-128 where supported. Store credentials
as host/template macros or protected runtime configuration, never in a template
export or Git. Limit device ACLs to the Zabbix poller address.

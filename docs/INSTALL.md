# Offline Installation

## Boundary

This procedure targets an explicitly approved RHEL 9.6 x86_64 system. A new
dedicated VM remains the production default. M3 used a separately authorized
home-lab exception: the existing dual-purpose host `192.168.1.91`, after a
read-only coexistence gate proved its PostgreSQL/NetBox state could be
preserved. This procedure consumes the accepted M1 release without altering it
and does not itself authorize creating or changing any target.

The target must start with SELinux Enforcing and must have root access,
`python3`, `dnf`, `sha256sum`, `systemctl`, `systemd-creds`, and `openssl`.
External repositories may be unavailable. The installer deliberately disables
all repository IDs except `zabbix-offline` for every package transaction.

## Inputs

Prepare these inputs on the target:

1. Extract the accepted M1 archive under `/opt/zabbix-offline/release`. Preserve
   `BUILD-INFO.json`, `SHA256SUMS`, `rpm-lockfile.txt`, `compat/`, and
   `repository/` together.
2. Place the M2 `installer/` directory beside the release content or supply its
   absolute path directly.
3. Copy `installer/examples/installer-vars.yml` to a root-owned environment file
   outside the repository and replace every example value.
4. Create a root-owned `0400` or `0600` database-password file. It must contain
   one 24-128 character value using `A-Z`, `a-z`, `0-9`, or `_!@%^+=.,:-`.
5. When TLS is enabled, provide a certificate for the configured web hostname
   and a matching root-owned `0400` or `0600` private key. The certificate must
   retain at least the configured minimum lifetime (30 days by default).

No password, private key, API token, SNMP community, or corporate certificate
belongs in Git.

## Preflight and install

Run the non-mutating preflight first:

```bash
sudo installer/bootstrap.sh \
  --release-root /opt/zabbix-offline/release \
  --vars /root/zabbix-install-vars.yml \
  --db-password-file /root/zabbix-db-password \
  --preflight-only
```

Expected terminal status is `RESULT=PASS_PREFLIGHT`. Then run the same command
without `--preflight-only` to converge the target. The bootstrap verifies the
M1 `SHA256SUMS` and M2 `MANIFEST.sha256` before any package transaction. It also
requires exact RHEL 9.6, x86_64, and SELinux Enforcing.

The install sequence is offline repository, OS guardrails, PostgreSQL, TLS,
Zabbix Server, nginx/PHP, Agent 2, vendor SELinux policy, firewalld, backup
tooling, verification, and release-state recording. Any missing package,
checksum mismatch, unsupported target, empty firewall source list, invalid TLS
input, or unexpected release transition fails closed.

## Check and verify

After a successful bootstrap, useful non-mutating planning is available with:

```bash
sudo installer/bootstrap.sh \
  --release-root /opt/zabbix-offline/release \
  --vars /root/zabbix-install-vars.yml \
  --db-password-file /root/zabbix-db-password \
  --check
```

Fresh-target check mode cannot predict PostgreSQL initialization, schema import,
encrypted credential creation, service starts, repository probes, or runtime
verification. Those narrow operations are skipped in check mode. Run check mode
on the converged target to assess configuration drift.

Run installed-state verification independently with `--verify-only`. A failure
is a release gate, not a reason to enable another repository or disable a
security control.

## M3 observed lab deployment

M3 kept the OS hostname `netbox-dev` and configured logical Zabbix identity
`ZABBIX-01`. Lab-only values live in `environments/lab/m3-zabbix.yml`; passwords
and TLS private material remain in root-only files outside Git. The accepted
release is under `/opt/zabbix-offline/release`, Zabbix uses HTTPS 8443, and the
existing NetBox nginx listeners remain on 80/443.

The current installer completed a zero-change convergence and zero-change check
mode on the rebooted target. This host is now a runtime system and must not be
treated as a pristine Build VM. Future artifact builds require isolated fresh
installroots or a separate clean build host. See `evidence/m3/ACCEPTANCE.md`.

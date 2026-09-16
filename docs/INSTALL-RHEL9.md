# Install on RHEL 9.6

## Preconditions

- A fresh RHEL 9.6 x86_64 VM with SELinux Enforcing.
- A named deployment account with SSH access and controlled sudo permission for the approved deployment commands.
- A DNS name and explicit corporate source CIDRs.
- Either approved connected repository access or an extracted offline bundle.
- No pre-existing Zabbix application database.

Direct root SSH access is not required. The deployment entry points themselves require root execution, so the deployment account should be permitted to run the approved root-owned scripts with sudo. `/opt/Zabbix` must remain root-owned and non-writable by the deployment account.

## Recommended production configuration path

Create the runtime configuration outside Git and outside `/root`:

```bash
sudo /usr/bin/install -d -o root -g root -m 0750 /etc/zabbix-deployment

sudo /usr/bin/install -o root -g root -m 0600 \
  /opt/Zabbix/.env.example \
  /etc/zabbix-deployment/zabbix-install.env

sudoedit /etc/zabbix-deployment/zabbix-install.env
```

The configuration file must remain root-owned with mode `0400` or `0600`.

Enter the operator-supplied deployment password for both password variables. Do not put the password in command history or copy it into the repository. The current qualified release requires the database and Admin bootstrap passwords to match.

Use:

```text
INSTALL_MODE=airgapped
OFFLINE_BUNDLE_ROOT=/opt/zabbix-offline/release-tree
ZABBIX_TIMEZONE=Asia/Riyadh
TLS_ENABLED=false
ZABBIX_FRONTEND_PORT=80
```

for the first qualified production deployment path. Production TLS should be handled as a separate qualified change.

## Install and verify

```bash
sudo /opt/Zabbix/install.sh \
  --config /etc/zabbix-deployment/zabbix-install.env

sudo /opt/Zabbix/verify.sh \
  --config /etc/zabbix-deployment/zabbix-install.env
```

After verification, independently inspect SELinux AVCs:

```bash
sudo /usr/sbin/ausearch -m AVC,USER_AVC -ts boot
```

The installer fails on OS/version mismatch, unsafe secret permissions, unapproved package source, lock drift, partial schema import, or operational data in an existing Zabbix database. It has no automatic database-destruction mode. A clean rerun converges; a database with added hosts/users is refused.

## VM storage baseline

For the initial 100 GB VM:

```text
/boot              2 GB
swap                6 GB
/var/lib/pgsql     55 GB
/                  remaining space (~37 GB)
```

XFS with LVM is preferred. No separate `/opt` partition is required.

## What to change in production

- DNS name, server identity, and IP addressing.
- Web, server, and agent firewall source CIDRs.
- SNMPv3 usernames, authentication/privacy passphrases, and context on hosts.
- Optional NetBox and Zabbix API URLs, CA files, and credentials.
- Production TLS only after the TLS path is separately qualified.

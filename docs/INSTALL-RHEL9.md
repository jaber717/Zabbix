# Install on RHEL 9.6

## Preconditions

- A fresh RHEL 9.6 x86_64 VM with SELinux Enforcing.
- Root access and explicit corporate source CIDRs.
- A DNS name and, for production TLS, a matching certificate and protected key.
- Either approved connected repository access or an extracted offline bundle.
- No pre-existing Zabbix application database.

Create the runtime file outside Git:

```bash
git clone --branch staging https://github.com/jaber717/Zabbix.git
cd Zabbix
sudo install -o root -g root -m 0600 .env.example /root/zabbix-install.env
sudoedit /root/zabbix-install.env
```

Enter the deployment password supplied by the operator for both password
variables. Do not quote it as shell code, put it in command history, or copy it
into the repository. Use `INSTALL_MODE=airgapped` with an extracted bundle path,
or `INSTALL_MODE=connected`. Set `ZABBIX_TIMEZONE=Asia/Riyadh`. The recommended
initial non-TLS lab port is 80; production should set `TLS_ENABLED=true` and a
corporate-approved HTTPS port and certificate.

Install and verify:

```bash
sudo ./install.sh
sudo ./verify.sh
```

The installer fails on any OS/version mismatch, unsafe secret permissions,
unapproved package source, lock drift, partial schema import, or operational
data in an existing Zabbix database. It has no automatic database-destruction
mode. A clean rerun converges; a database with added hosts/users is refused.

## What to change in production

- DNS name, server identity, and IP addressing.
- Web, server, and agent firewall source CIDRs.
- TLS certificate/private-key paths and the certificate itself.
- SNMPv3 usernames, authentication/privacy passphrases, and context on hosts.
- Optional NetBox and Zabbix API URLs, CA files, and credentials.

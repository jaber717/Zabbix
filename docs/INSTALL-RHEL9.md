# Install on RHEL 9.x x86_64

## Preconditions

- A dedicated RHEL 9.x x86_64 host with SELinux Enforcing.
- A named deployment account with SSH and controlled sudo for approved commands.
- A DNS name and, for production TLS, a matching certificate and protected key.
- Either approved connected repository access or an extracted offline bundle.
- No pre-existing operational Zabbix database; an unchanged stock deployment
  from this installer can be rerun. Added hosts/users are intentionally refused.
- Bash, Git, Python 3 with the RHEL DNF bindings, DNF, RPM, coreutils, sudo,
  subscription-manager, and the Red Hat RPM signing key must be present.
- CONNECTED: authorized configured BaseOS/AppStream repository IDs and HTTPS
  access to the approved official Zabbix repositories and signing-key URLs.
  Configure corporate DNS, proxy, trust, and entitlement using normal host
  administration. The project never registers the host or changes release pins.

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
INSTALL_MODE=connected
OFFLINE_BUNDLE_ROOT=
ZABBIX_TIMEZONE=Asia/Riyadh
```

for the requested CONNECTED path. Choose TLS, port, firewall sources and
certificate paths under corporate policy; TLS is not qualified by the HTTP
lab rerun. Any installed IANA timezone is supported. AIRGAPPED instead requires
an explicit compatible bundle. `/root/zabbix-install.env` remains the default;
the restricted-sudo path above is supported with `--config`.

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

Inspect `/etc/zabbix-offline/` before installation. Do not delete it to get
past a guard. `bundle-root` is an installed-bundle pointer used by verification;
CONNECTED installation stages from the current clean Git commit each time.
AIRGAPPED explicitly selects its bundle, whose recorded minor version must
match the target. `release.json` and `clean-seed-verified` protect lifecycle
and database state. Existing encrypted credentials are machine-local.

## Runtime keys

Required: `INSTALL_MODE`, `ZABBIX_SERVER_HOSTNAME`, `ZABBIX_WEB_SERVER_NAME`,
`ZABBIX_TIMEZONE`, `ZABBIX_FRONTEND_PORT`, `ZABBIX_DB_PASSWORD`,
`ZABBIX_ADMIN_PASSWORD`, `TLS_ENABLED`, `FIREWALL_WEB_SOURCES`,
`FIREWALL_SERVER_SOURCES`, `FIREWALL_AGENT_SOURCES`.

Conditional: `OFFLINE_BUNDLE_ROOT` for AIRGAPPED only; `TLS_CERTIFICATE_FILE`
and `TLS_PRIVATE_KEY_FILE` when TLS is enabled. The unencrypted private key must
be root-owned mode 0400/0600 and the certificate must match the web identity,
match the key, and remain valid for at least 30 days. Use an approved HTTPS
port already permitted by the host's SELinux `http_port_t` policy. DNS, routes,
proxy and CA trust are host prerequisites, not application configuration.

Optional: `BASEOS_REPO` and `APPSTREAM_REPO`, defaulting to the standard
`rhel-9-for-x86_64-baseos-rpms` and `rhel-9-for-x86_64-appstream-rpms` IDs.
Override them only with the host's authorized RHEL equivalents (for example,
Satellite). This does not authorize additional upstreams. Repository URLs,
client certificates and proxy secrets stay in the administrator's DNF/RHSM
configuration. Third-party and non-RHEL replacement content is unsupported.

Values are literal `KEY=value`, never shell-sourced. Unknown, duplicate, empty
required keys fail. Both passwords must match under the existing bootstrap
policy and use 12-128 characters from `A-Za-z0-9_!@%^+=.,:$-`. No secret default
exists. Source networks are explicit comma-separated CIDRs; no broad network
default is invented. Protect the file outside Git with root ownership and
0400/0600 mode. Do not overwrite an existing production runtime file with the
example during a rerun.

## What to change in production

- DNS name, server identity, and IP addressing.
- Web, server, and agent firewall source CIDRs.
- SNMPv3 usernames, authentication/privacy passphrases, and context on hosts.
- Optional NetBox and Zabbix API URLs, CA files, and credentials.
- Production TLS only after the TLS path is separately qualified.

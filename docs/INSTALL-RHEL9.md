# Install on RHEL 9.x x86_64

## Preconditions

- A dedicated RHEL 9.x x86_64 host with SELinux Enforcing.
- Root access and explicit corporate source CIDRs.
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
or `INSTALL_MODE=connected` with `OFFLINE_BUNDLE_ROOT` empty. Set
`ZABBIX_TIMEZONE` to an installed IANA timezone. The recommended
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
- TLS certificate/private-key paths and the certificate itself.
- SNMPv3 usernames, authentication/privacy passphrases, and context on hosts.
- Optional NetBox and Zabbix API URLs, CA files, and credentials.

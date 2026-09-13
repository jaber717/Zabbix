# Troubleshooting

## Installer stops before package work

Check `/etc/redhat-release`, `uname -m`, `getenforce`, runtime file ownership and
mode, bundle checksums, and `BUILD-INFO.json`. In connected mode, verify the
staging host has an identity and the exact BaseOS/AppStream sources named in the
compatibility profile. Do not broaden repositories to fix a missing dependency.

## PostgreSQL

Confirm PostgreSQL 16 is active and listening only on loopback. Test TCP as the
application role using protected environment input, not a command-line password.
Review the managed SCRAM entries in `pg_hba.conf`. A partial schema import or a
database with non-stock hosts/users must be treated as a hard stop.

## Frontend or server

Run `nginx -t`, `php-fpm -t`, `systemctl status` for PostgreSQL, Zabbix Server,
Agent 2, PHP-FPM, and nginx, and review `journalctl -u zabbix-server`. Check the
certificate SAN, key match, expiry, DNS, and configured port. Do not disable TLS
validation to hide an identity error.

## SELinux

Keep Enforcing. Inspect `ausearch -m AVC,USER_AVC -ts boot`; confirm the vendor
Zabbix policy and the two documented booleans. Diagnose the exact denied access.
Do not run a broad `audit2allow` or set permissive mode.

## Huawei/FortiGate SNMP

Start with a single authenticated `sysUpTime.0` query using credentials supplied
securely. Verify UDP/161 routing, device ACL, SNMPv3 engine/user/context,
algorithms, and clock. Then execute discovery in Zabbix and inspect the precise
unsupported-item error. Use official discovery filters before changing items.

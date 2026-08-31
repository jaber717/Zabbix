# Decisions

## M1 compatibility and source decisions

### Python ABI

- **Candidates:** CPython 3.9 from RHEL BaseOS and CPython 3.11/3.12 from RHEL
  AppStream were all observed in approved RHEL 9.6 sources.
- **Decision:** CPython 3.11, with package names `python3.11`,
  `python3.11-pip`, `python3.11-setuptools`, and `python3.11-wheel`.
- **Why:** It is RHEL-native, offers a longer application horizon than the base
  platform's 3.9 ABI, and avoids adopting 3.12 solely because it is newest. It
  balances lifecycle and offline operational simplicity without introducing a
  compiler or third-party runtime repository.
- **Risks:** M4 has not defined `netbox-zabbix-sync` dependencies, so wheel
  compatibility is not yet proven. The wheel builder remains ABI-parameterized,
  requirements are deliberately empty, and M4 must hash-lock and test the real
  transitive set. A dependency incompatible with 3.11 would require an explicit
  compatibility-profile decision, not an implicit fallback.

### Target content

Zabbix is pinned to `7.0.30-release1.el9`. The bundle includes PostgreSQL and
SQLite proxy packages but excludes the MySQL proxy because no approved
operational requirement exists. `zabbix-web-service` is included to keep the
approved web/reporting component available without installing it during M1.
`zabbix-selinux-policy` is included as the vendor-provided SELinux integration.

RHEL `ansible-core` is included for the future installer architecture. No
external collection is required by M1; future roles should prefer
`ansible.builtin`, and any later collection must be explicitly versioned,
checksummed, and vendored.

### Module metadata

The repository preserves selected original AppStream modulemd documents for
PostgreSQL 16, PHP 8.3, and nginx 1.24. The broad `modulesync --resolve` download
was measured and rejected because it pulled build/source/i686 content unrelated
to the runtime closure. Local-only module listing/enabling and installation are
the acceptance criteria.

### Repository metadata signing

RPM `gpgcheck=1` is mandatory. `repo_gpgcheck=0` is explicit until the project
has an approved independent signing key and custody process. A private key stored
beside the artifact would add no independent trust and is prohibited.

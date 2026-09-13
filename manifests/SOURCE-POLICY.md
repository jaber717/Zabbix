# RPM source policy

- RHEL BaseOS may supply operating-system dependencies.
- RHEL AppStream may supply operating-system dependencies and the selected
  PostgreSQL 16, PHP 8.3, and nginx 1.24 module content.
- The official Zabbix 7.0 repository may supply only Zabbix packages.
- The official Zabbix non-supported RHEL 9 x86_64 repository may supply only
  `fping-0:5.1-1.el9.x86_64`.
- Any other package from the non-supported source fails the build.
- EPEL is neither enabled nor used.

`rpm-lockfile.txt` records exact NEVRA, architecture, repository ID, and SHA-256.
The staging pipeline independently validates repository metadata, signing-key
fingerprints, every RPM signature, the `fping` exception, and source isolation.

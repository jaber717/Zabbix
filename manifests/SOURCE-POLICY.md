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
CONNECTED staging generates that lock from the selected host's authorized
repository content. The tracked historical lock is used only by explicit frozen
build comparison, never imposed on another minor's CONNECTED dependency set.
Application versions and streams remain pinned by the compatibility profile.
The staging pipeline independently validates repository metadata, signing-key
fingerprints, every RPM signature, the `fping` exception, and source isolation.

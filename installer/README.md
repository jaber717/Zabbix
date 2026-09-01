# Offline Installer

This directory is the M2 installer for the immutable M1 RHEL 9.6 x86_64
release. `bootstrap.sh` verifies both release and installer checksums, enforces
the target/SELinux prerequisites, creates one `file://` repository, installs
`ansible-core` from that repository with every other repository disabled, and
runs the separated Ansible roles.

Use `examples/installer-vars.yml` only as a shape reference. It contains
documentation-only RFC 5737 values and must be copied outside the repository
and replaced for each environment. TLS key material and the database password
are operator inputs and are never part of this tree.

Entry points:

- `bootstrap.sh --preflight-only`: checksum, target, SELinux, and input checks;
  no target changes.
- `bootstrap.sh`: bootstrap and converge the platform.
- `bootstrap.sh --check`: useful check mode on an already bootstrapped target.
- `bootstrap.sh --verify-only`: installed-target verification.
- `playbooks/backup.yml`: explicitly create and verify a full backup.
- `playbooks/upgrade-preflight.yml`: non-mutating upgrade readiness gate.

See `docs/INSTALL.md`, `docs/OPERATIONS.md`, `docs/BACKUP-RESTORE.md`, and
`docs/UPGRADE.md` before operating the installer.

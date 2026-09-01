# M3 Start Record

Date: 2026-09-01

Authorized milestone: M3 — deploy and runtime-validate Zabbix on the existing
RHEL 9.6 VM only.

Authorized target:

- IP: `192.168.1.91`
- Pre-M3 hostname: `netbox-dev`
- Access: SSH key authentication as `jaber`, with existing passwordless sudo
- Architecture amendment: reuse the former Build VM as the home-lab Zabbix
  runtime host; do not create another VM

Repository baseline:

- Branch: `main`
- M2 closeout: `5fd58e7f669a46a063d90877dd39e4bf7b07171c`
- Initial worktree: clean
- External push: not authorized

Immutable release input:

- File: `zabbix-rhel96-offline-1.0.0-build1.tar.gz`
- Size: `178093296` bytes
- SHA256: `dbcd9a1185a21f1bc44bff356f06088ac63d77a5bb8fe539ad573280d9cef42b`

Safety boundary:

- Complete a read-only host and PostgreSQL coexistence preflight before
  convergence.
- Stop rather than reinitialize, overwrite, drop, or remove existing database
  state.
- Do not touch another Proxmox guest, Proxmox networking/storage, NetBox, M4,
  or any external Git remote.

# M3 Evidence Index

The M3 acceptance decision is in `ACCEPTANCE.md`. `START.md` and
`PREFLIGHT-ASSESSMENT.md` record the authorized boundary and coexistence gate;
`FINAL-AUDIT.md` records repository/evidence closure checks. The `raw/`
directory contains captured command, Ansible, API, reboot, backup, SELinux,
negative-test, and final safety outputs. `raw/SHA256SUMS` inventories the raw
evidence bytes.

No password, private TLS key, API token, backup payload, or RPM payload is
stored here. Runtime backups remain root-private on the authorized lab VM.

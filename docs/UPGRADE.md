# Upgrade and Rollback

M2 ships a v1 forward-upgrade gate; it does not perform a version upgrade. The
release state at `/etc/zabbix-offline/release.json` distinguishes fresh install,
same-release convergence, upgrade required, and unsupported downgrade.

Before any future upgrade, transfer the candidate offline release, verify it is
an approved artifact, create and verify a full PostgreSQL backup, and preferably
take an approved VM snapshot. Run:

```bash
sudo ansible-playbook installer/playbooks/upgrade-preflight.yml \
  --inventory installer/inventory/hosts.yml \
  --extra-vars @/root/zabbix-install-vars.yml \
  --extra-vars offline_release_root=/opt/zabbix-offline/candidate
```

The preflight verifies release checksums, exact RHEL/architecture compatibility,
release direction, free space of at least twice the candidate artifact size,
and the latest full backup. `RESULT=PASS` authorizes review of a later upgrade
transaction; it is not itself an upgrade.

A future upgrade procedure must stop the frontend and Zabbix Server, keep
PostgreSQL protected, install only from the candidate `file://` repository,
start PostgreSQL before Zabbix Server and the web stack, and run the complete
verification playbook. Record exact before/after release state and package
NEVRAs.

Database schema downgrade is unsupported. Rollback is the old offline package
set and configuration plus the verified pre-upgrade PostgreSQL backup or VM
snapshot. Never claim rollback from package downgrade alone after Zabbix has
advanced the schema.

# Backup and Restore

## Backup

The installer deploys a daily `zabbix-offline-backup.timer` and four guarded
tools under `/usr/local/sbin`. A full backup contains a PostgreSQL custom-format
dump, managed configuration archive, metadata, and SHA256 checksums. A `config`
backup omits the database dump and is not sufficient for database recovery.

Create a full backup through Ansible:

```bash
sudo ansible-playbook installer/playbooks/backup.yml \
  --inventory installer/inventory/hosts.yml \
  --extra-vars @/root/zabbix-install-vars.yml
```

Or invoke `/usr/local/sbin/zabbix-offline-backup full`. The script builds a
private partial directory, validates `pg_restore --list` and every checksum,
and publishes the final directory only after those checks pass. Verify any
candidate again with:

```bash
sudo /usr/local/sbin/zabbix-offline-verify-backup /var/backups/zabbix-offline/BACKUP-full
```

## Restore preflight

Run the non-mutating gate first:

```bash
sudo /usr/local/sbin/zabbix-offline-restore-preflight /var/backups/zabbix-offline/BACKUP-full
```

It verifies controlled path containment, checksums, archive readability,
PostgreSQL dump readability, and release-state presence. It deliberately prints
`RESTORE_ACTION=NOT_EXECUTED` and makes no change.

## Authorized restore sequence

A restore replaces live data and requires separate authorization, maintenance
window, target confirmation, and a rollback snapshot or backup. The operator
procedure is:

1. Record current release state and take a new verified full backup when the
   current database is readable.
2. Stop nginx, PHP-FPM, Zabbix Server, and Agent 2; then stop PostgreSQL only
   when required by the selected recovery method.
3. Restore configuration to a staging directory, review paths/ownership, and
   copy only the approved files. Never overwrite the encrypted credential with
   an unrelated secret.
4. Restore the custom dump into a deliberately prepared empty compatible
   database using `pg_restore --exit-on-error`; the normal installer contains
   no database drop/reset path.
5. Start PostgreSQL, Zabbix Server, PHP-FPM, nginx, and Agent 2 in dependency
   order, then run `installer/playbooks/verify.yml`.
6. Retain the pre-restore backup/snapshot until acceptance.

No restore was executed in M2 because no dedicated disposable RHEL service VM
was authorized. Restore status is `NOT-EXECUTED`, not PASS.

## M3 observed result

On the authorized lab runtime, full backup
`20260901T025816Z-full` was published root-owned `0700` with root-owned `0600`
files only after the PostgreSQL custom dump, configuration archive, and all
SHA256 checks passed. Independent verification and archive listings passed.
The configuration backup contained the expected managed files, no persistent
`DBPassword`, no encrypted database-password input, no administrator-password
input, and no TLS private-key tree.

The restore preflight passed and printed `RESTORE_ACTION=NOT_EXECUTED`. No live
database was replaced and no temporary restore database was created; destructive
restore requires separate authorization. Raw evidence is in
`evidence/m3/raw/m3-backup-validation-attempt3.log`.

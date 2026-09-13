# Backup and restore

The installer deploys a root-only backup command and daily systemd timer. No
backup or database dump belongs in Git.

## Configuration-focused backup

```bash
sudo /usr/local/sbin/zabbix-offline-backup config
```

This preserves managed configuration and a configuration-oriented database
export while excluding high-volume history/trend data where the deployed helper
supports that mode. It is useful for rebuilding policy but is **not** complete
disaster recovery.

## Full operational backup

```bash
sudo /usr/local/sbin/zabbix-offline-backup full
sudo /usr/local/sbin/zabbix-offline-verify-backup /var/backups/zabbix-offline/<backup-directory>
```

Full mode retains the operational database and configuration. Store it on
protected, encrypted backup media and test restore separately.

## Restore

Restoration is intentionally not automatic. On an isolated replacement host,
verify the backup, match the recorded release/version, stop application writers,
restore PostgreSQL and configuration using the organization's approved runbook,
restore labels, start services, and run `verify.sh`. The installed
`zabbix-offline-restore-preflight` performs only non-mutating validation; it does
not overwrite a database. Never test restore on the source or production host.

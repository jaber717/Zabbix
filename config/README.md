# Runtime configuration

The tracked `.env.example` intentionally contains variable names only. Copy it
to `/root/zabbix-install.env`, set owner `root` and mode `0600`, then edit it
outside the repository. `install.sh` parses it as inert `KEY=value` data: it
does not use shell `source`, interpolation, or `eval`.

Comma-separate firewall CIDRs. Use documentation ranges while testing examples;
replace them with the corporate management networks at deployment time.

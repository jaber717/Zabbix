# Decision log

| Decision | Result |
|---|---|
| Target | RHEL 9.x x86_64; offline bundles remain target-minor/content specific. |
| Zabbix | Exact 7.0.30 (`7.0.30-release1.el9`) pin. |
| Database | Local PostgreSQL 16, TCP loopback, SCRAM-SHA-256, UTF8/template0. |
| Frontend | nginx/PHP-FPM; port is explicit, 80 recommended for non-TLS lab use and TLS required for production. |
| Package flow | Connected staging and airgapped install converge on one signature-checked local repository. |
| RPM publication | No RPM is committed or published through GitHub. |
| Huawei baseline | Stock `Huawei VRP by SNMP`; no redundant export. |
| Huawei additions | None: exact family OIDs and real-device testing were unavailable. |
| FortiGate baseline | Stock `FortiGate by SNMP`; its observed 7.0.30 structure includes HA, VPN, and SD-WAN discovery. |
| NetBox sync | Reusable standard-library reconciler retained, sanitized, optional, dry-run oriented, and disabled by default. |
| Database migration | None. Only stock seed content is accepted. |
| Sizing | Conservative initial baseline; final scale is unknown. |
| Release branch | `staging` until clean install, rerun, reboot, and full `verify.sh` pass on a disposable VM. |

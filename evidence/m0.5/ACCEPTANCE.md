# M0.5 Acceptance

| Gate | Status | Evidence |
|---|---|---|
| RHEL BaseOS repository ID confirmed | PASS | `pre-change/repository-state.txt` |
| RHEL AppStream repository ID confirmed | PASS | `pre-change/repository-state.txt` |
| BaseOS usable | PASS | `post-change/rhel-source-verification.txt`, clean-context attempt 4 |
| AppStream usable | PASS | `post-change/rhel-source-verification.txt`, clean-context attempt 4 |
| RHEL release remains pinned to 9.6 | PASS | Pre/post/final evidence and clean-context attempt 4 |
| Real RHEL module streams captured | PASS | `post-change/rhel-source-verification.txt` |
| Python availability captured from approved sources | PASS | `post-change/rhel-source-verification.txt` |
| Official Zabbix RHEL 9 repository reachable | PASS | `post-change/zabbix-source-verification.txt` |
| Zabbix 7.0.30 package family availability verified | PASS | Eleven exact package-family rows in Zabbix source evidence |
| Clean installroot/context accesses approved sources | PASS | `clean-context/source-resolution-attempt-4.txt` |
| NetBox offline repositories excluded | PASS | Attempt 4 repolist and resolved repo IDs |
| No packages installed/updated on host OS | PASS | Host RPM hash unchanged; clean RPM count before/after zero |
| No module state changed | PASS | Host module-state hash unchanged |
| No secrets committed | PASS | Staged-content scans found no private-key marker, credential-like literal, or unredacted subscription identity |
| Build source evidence committed | PASS | Commit `b2180c00d0a6029a65996055ae7becbcddc5f0b7` |

Attempts 1–3 are retained as real failed setup evidence. They failed before
repository access because RPM would not initialize beneath the world-writable
`/var/tmp` hierarchy. Attempt 4 used a validated disposable root under `/var/lib`,
completed successfully, and removed the root afterward.

# M2 Acceptance Record

Date: 2026-09-01

Scope: offline installer and configuration automation only. No ZABBIX-01 VM was
created or changed, M3 was not started, and NetBox was not accessed.

## Executed gates

| Gate | Status | Evidence |
|---|---|---|
| Required role/playbook structure | PASS | `raw/static-tests.txt` |
| Python source syntax | PASS | `raw/static-tests.txt` |
| Shell syntax | PASS | `raw/static-tests.txt` |
| Helper negative/unit tests | PASS (6/6) | `raw/static-tests.txt` |
| Forbidden architecture/safety pattern scan | PASS | `raw/static-tests.txt` |
| Every installer DNF task source-bounded | PASS | `raw/static-tests.txt` |
| Installer checksum manifest | PASS (56 entries) | `raw/static-tests.txt` |
| All four playbooks parse with RHEL Ansible | PASS | `raw/ansible-syntax.txt` |
| `ansible-core` resolves in a fresh root from only accepted M1 repository | PASS | `raw/offline-controller-resolution.txt` |
| Fresh-root RPM signatures use accepted Red Hat key | PASS | `raw/offline-controller-resolution.txt` |
| Build VM host RPM state unchanged by fresh-root proof | PASS | `raw/offline-controller-resolution.txt` |
| Accepted M1 tracked inputs unchanged | PASS | `raw/final-safety-audit.txt` |
| Authored whitespace and secret/lab leakage audit | PASS | `raw/final-safety-audit.txt` |
| No RPM payload added to Git | PASS | `raw/final-safety-audit.txt` |

## Runtime gates

| Gate | Status | Reason / next execution point |
|---|---|---|
| Fresh RHEL 9.6 platform converge | NOT-EXECUTED | Requires the dedicated disposable/target VM; creating ZABBIX-01 is M3. |
| Second-run idempotency | NOT-EXECUTED | Requires a successfully converged dedicated target in M3. |
| Converged-target `--check` | NOT-EXECUTED | Requires the same dedicated target in M3. |
| systemd service and reboot behavior | NOT-EXECUTED | A chroot cannot truthfully test a booted service manager. |
| SELinux policy/AVC behavior | NOT-EXECUTED | Requires a booted Enforcing target with running workload. |
| firewalld rules and network reachability | NOT-EXECUTED | Requires the approved target addresses and source networks. |
| PostgreSQL initialization/schema/runtime credential | NOT-EXECUTED | Installing the Zabbix runtime on the M1 Build VM is prohibited. |
| nginx/PHP frontend and Zabbix/API response | NOT-EXECUTED | Requires the M3 target, hostname, certificate, and runtime services. |
| Backup execution | NOT-EXECUTED | Requires a real managed database/configuration set. |
| Restore execution | NOT-EXECUTED | Destructive test requires a disposable M3 target and separate restore authorization. |
| Actual version upgrade/rollback | NOT-APPLICABLE | M2 delivers v1 preflight/workflow; no second release is approved. |

## Verdict

M2 implementation and every executable M2 static/offline gate passed. The
remaining runtime tests are explicitly assigned to M3 by the authorized test
boundary and are not represented as PASS.

**M2 ACCEPTED — M3 READY, but M3 has not started.**

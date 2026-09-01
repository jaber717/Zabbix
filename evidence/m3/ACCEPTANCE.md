# M3 Acceptance Record

Date: 2026-09-01

Scope: deploy and runtime-validate logical `ZABBIX-01` only on the existing
RHEL 9.6 VM at `192.168.1.91` (`netbox-dev`). No VM was created, no other guest
or Proxmox setting was changed, no NetBox write/integration occurred, M4 was not
started, and nothing was pushed externally.

## Accepted inputs and coexistence

- The accepted M1 archive was staged unchanged at 178093296 bytes and SHA256
  `dbcd9a1185a21f1bc44bff356f06088ac63d77a5bb8fe539ad573280d9cef42b`.
- Release `SHA256SUMS` and the deployed M2 installer's 57-entry manifest passed.
- The host is RHEL 9.6 x86_64 with SELinux Enforcing, 4 CPUs, 11 GiB RAM, and
  adequate free disk at preflight.
- The pre-existing PostgreSQL 16 cluster, 198-table NetBox database, NetBox
  services, Redis, and nginx listeners on 80/443 were treated as meaningful and
  preserved. Zabbix uses a separate database and HTTPS 8443 listener.
- No `initdb`, database drop, destructive restore, blanket `pg_hba.conf`
  replacement, or OS-hostname rename was performed.

## Executed gates

| Gate | Status | Observed result / raw evidence |
|---|---|---|
| Read-only coexistence preflight | PASS | `preflight.txt`, `PREFLIGHT-ASSESSMENT.md` |
| Accepted artifact staging and hash | PASS | `artifact-staging.txt` |
| M1 release and M2 installer manifests | PASS | `m3-safety-closeout.log` |
| Package-source isolation | PASS | Every installer DNF action disabled all repositories except `zabbix-offline`; local-only verification passed. `repository-isolation-preconverge.txt`, convergence logs |
| First successful converge | PASS | Attempt 15: `ok=123 changed=3 failed=0 skipped=13`. Earlier attempts failed closed while bounded runtime issues were corrected. `m3-first-converge-attempt15.log` |
| PostgreSQL coexistence/schema | PASS | PostgreSQL 16.10 active; databases `netbox`, `postgres`, `zabbix`; Zabbix has 203 public tables, DB version `7000000/7000030`, zero public relations owned by another role; NetBox remains 198 tables. `m3-safety-closeout.log` |
| Required packages | PASS | Zabbix 7.0.30, PostgreSQL 16, nginx 1.24, PHP 8.3, Agent 2, vendor SELinux policy, firewalld, and `fping-5.1-1.el9` installed; MySQL/proxy/Java gateway variants absent. `m3-safety-closeout.log` |
| Server and local Agent 2 | PASS | Services enabled/active; 10051 and 10050 listen; API host availability and passive interface are `1`; `agent.ping=1`; recent hostname/uptime values collected. `m3-final-api-health.log` |
| nginx/PHP/frontend | PASS | nginx and PHP-FPM enabled/active; Zabbix HTTPS 8443 returns 200 without the setup wizard; NetBox HTTPS remains 200 on 443; Apache is inactive and masked. `m3-safety-closeout.log` |
| API/application/basic queue | PASS | API 7.0.30; logical host `ZABBIX-01`; two monitored internal queue items both report zero. The `queue.get` method is not exposed by this API and is `NOT-APPLICABLE`, not inferred. `m3-final-api-health.log` |
| Unsupported-item review | PASS | 12 of 160 monitored enabled items (7.50%) are unsupported: 11 map to intentionally disabled optional subsystems and one NIC-speed template item receives `-1000000`. This is bounded and recorded for later template tuning, not represented as zero. `m3-final-api-health.log` |
| SELinux | PASS | Enforcing before, during, and after reboot. Seventy same-path `zabbix_t` search denials for `/var/kerberos/krb5` occurred only during startup; no new denial appeared during the observation window. Linked Kerberos libraries explain the probe; no access requirement, guessed boolean, or custom allow rule was introduced. `m3-avc-since-boot.log`, `m3-avc-diagnosis.log` |
| firewalld | PASS | Active/enabled; only source-restricted `192.168.1.0/24` rich rules were added for 8443, 10050, and 10051. Pre-existing NetBox 80/443 exposure was preserved. `m3-safety-closeout.log` |
| TLS and secrets | PASS | Lab self-signed TLS CN/SAN matches `zabbix-01.lab` and `192.168.1.91`; SHA256 fingerprint recorded. The key is root `0600`; encrypted credential is root `0600`; host credential key is root `0400`; runtime configs are group-bounded. No persistent `DBPassword` or process-command secret was observed. `m3-safety-closeout.log` |
| Second convergence | PASS | First clean second run: `ok=121 changed=0 failed=0 skipped=14`. `m3-second-converge-attempt1.log` |
| Final current-code idempotency | PASS | After all bounded fixes: `ok=121 changed=0 failed=0 skipped=14`. `m3-final-idempotency-e060454.log` |
| Converged-target check mode | PASS | Current code: `ok=77 changed=0 failed=0 skipped=58`; skipped operations are the documented mutating/runtime-only carve-outs. CIDR and TLS input checks now execute read-only in check mode. `m3-final-check-mode-e060454.log` |
| Authorized reboot | PASS | Boot ID changed to `422a5647-8a00-474e-a6cc-64fb25c3c0d3`; PostgreSQL, Zabbix, Agent 2, nginx, PHP-FPM, firewalld, NetBox, Redis, endpoints, listeners, schema, and collection recovered. `m3-pre-reboot-state.log`, `m3-post-reboot-validation.log`, `m3-post-reboot-verify-only.log` |
| Full backup | PASS | Root-private full dump/config/checksum backup `20260901T025816Z-full` passed independent verification, checksum checks, archive listing, expected-content checks, and secret exclusions. `m3-backup-validation-attempt3.log` |
| Restore | NOT-EXECUTED | Non-mutating restore preflight passed and explicitly returned `RESTORE_ACTION=NOT_EXECUTED`; destructive live restore was not authorized. `m3-backup-validation-attempt3.log` |
| Safe negative suite | PASS | Corrupt artifact, missing secret, invalid CIDR, mismatched TLS key, and unapproved dependency cases failed closed; post-test configuration/firewall/boot/runtime invariants remained unchanged. `m3-negative-tests.log` |
| Static/current installer tests | PASS | 17 unit tests, syntax, source/offline policy, and 57-entry manifest passed before current installer deployment. Git commits preserve the audit trail. |
| Safety closeout | PASS | All target services and both endpoints healthy, no failed units, accepted inputs intact, expected listeners and database contents present. `m3-safety-closeout.log` |

## Fail-closed corrections retained in the audit trail

The first successful convergence followed bounded failed attempts. Corrections
preserved the shared NetBox/PostgreSQL environment and addressed schema payload
ordering, systemd credential/runtime paths, SELinux runtime labels, schema
ownership, PID-file alignment, Apache guarding, exact firewalld locking,
handler application, check-mode safety, and root-private backup streaming.
Acceptance is based on the final successful runtime, zero-change convergence,
current-code check mode, reboot, backup, negative, and safety-closeout evidence;
no failed attempt was relabeled PASS.

## Build-host role transition

`192.168.1.91` is now the Zabbix home-lab runtime host and is no longer a
pristine runtime-free Build VM. M1 and M2 remain accepted because their gates
completed before this explicitly authorized transition. Future release builds
must use fresh isolated clean installroots or a separate clean build host.

## Verdict

Every required M3 runtime gate passed except the destructive restore, which is
truthfully `NOT-EXECUTED` after a passing non-mutating preflight. The bounded
unsupported-item and startup AVC findings are diagnosed, evidenced, and do not
block the platform gate. M4 remains subject to its existing NetBox permission
and version-compatibility blockers and separate authorization.

**M3 ACCEPTED — M4 READY.**

# M4 Test Results

## Fixture and client suite

The Python 3.9 target executed 29 sanitized fixture/unit/static tests: **PASS**.
Coverage includes pagination, authentication denial, timeout, HTTP error,
cross-origin pagination refusal, NetBox write-method refusal, stable device/VM
identity, rename and IP drift, mapped/unmapped/ambiguous attributes, missing and
duplicate IPs, denied metadata as UNKNOWN, create/update/unchanged plans, orphan
and template/group drift reporting, change-budget and apply gates, dry-run
default, safe template addition, absence of delete/unlink calls, and secret-free
reports.

Evidence: `raw/unit-tests-rhel.txt`.

## Installer regression and deployment

- Existing M2 static validation and 17 regression tests: **PASS**.
- Bash syntax and the regenerated 62-entry installer manifest: **PASS**.
- M4 role final deployment: `ok=14 changed=1 failed=0`, reflecting the final
  source update.
- Immediate second role run: `ok=13 changed=0 failed=0`.
- `systemd-analyze verify`: no output, exit success.
- systemd security exposure score: 3.8, `OK`.

Evidence: `raw/m2-regression-static.txt`, `raw/deploy-final.txt`,
`raw/deploy-idempotency.txt`, `raw/service-timer.txt`, and
`raw/service-security.txt`.

## Static safety

The installed runtime contained zero references to Zabbix `host.delete`, zero
template-unlink calls, zero literal NetBox POST/PATCH/PUT/DELETE requests, zero
`--apply` flag in the installed service, and zero plaintext token/password
assignments. Evidence: `raw/static-safety-audit.txt`.

# Phase 0 - baseline audit of the Daily Reporting RC2

Baseline: tag `daily-reporting-v1.0.0-rc2`, SHA `2fb5f19a2e8611e7f241f70ed1eb9b95a1d537bc`. Inspected: `docs/DAILY-REPORTING.md`,
`reporting/daily-reporting/` (collector, native helpers, config, systemd), `scripts/{install,verify,rollback}_daily_reporting.sh`
and `scripts/lib/daily-reporting-common.sh`, `scripts/build_offline_bundle.sh`, `tests/daily-reporting/`, `evidence/daily-reporting/`.
The RC2 baseline tests were re-run against the extended tree and pass (4 static, 6 unit, installer smoke, native-rollback).

## Reusable as-is (and reused)

| Component | Why it is kept |
|---|---|
| `report.json` schema `zabbix-daily-reporting-v1` + `load_config` | The single validated contract; the suite reads it for API URL, CA file, timezone, thresholds, classification patterns and SMTP settings and adds its own `suite.json` beside it. |
| Service account `zabbix-report`, `/etc/zabbix-daily-reporting/secrets.env` (0600, `EnvironmentFile`) | Credentials never reach argv, Git or the bundle. Same file feeds the suite units. |
| Installer layout (`/opt`, `/etc`, `/var/lib`, `/var/backups`), backup-before-change, config/secret preservation, `DAILY_REPORTING_ROOT` isolated-root testing | Extended, not replaced. |
| Offline bundle (`MANIFEST.sha256`, deterministic tar) | Extended with wheels. |
| Native Zabbix scheduled-PDF helpers and drop-in baseline/rollback logic | Untouched; remains optional and independent. |
| TLS handling (`ssl.create_default_context(cafile)`) | Same pattern in the new API client; verification is never disabled. |

## Missing

* Period engine: only `previous_day`; no weekly/monthly; no explicit half-open window handling beyond one subtraction.
* Historical data: no `history.get` / `trend.get`; "availability" is the *current* interface state; CPU/memory use the *latest value*.
* Output formats: HTML + JSON only (no PDF, no XLSX); email carries HTML only.
* No coverage/confidence, no per-device availability %, no incident duration/MTTR.
* No idempotency (every run rewrites), no manifest/checksums, non-atomic `write_text`, default umask permissions.

## Risky

| Finding | Effect | Handling in the suite |
|---|---|---|
| `item.get` over every monitored host with only a `limit` | An unrestricted item scan; hitting the limit silently truncates | Targeted `item.get` (key search per needed metric, hostids chunked, interface tag filter for WAN) with `limit+1` truncation detection. RC2 collector left as is. |
| `limit` on `host.get`/`problem.get`/`event.get` never checked | Silent partial reports | Every bulk call detects truncation, splits windows/batches, and reports what stays partial in the report itself. |
| Problems mapped to hosts through `trigger.get` | Multi-host triggers and removed triggers lose attribution | Hosts come from `event.get selectHosts`; one incident, listed against every host. |
| Retention by `mtime` of any `daily-network-health-*.*` | Could delete a file the operator touched/copied | Suite retention removes only runs that have its own manifest and only the files it lists. |
| `stale_data_minutes` from newest `lastclock` of an arbitrary item | A device with one chatty item is never stale | Staleness is judged on the ICMP item; devices without one are "not evaluated", not "fine". |
| Raw CPU/memory exceptions from the latest value | Not a historical statistic | Never used. The suite uses trends/history only and labels hourly percentiles as such. |
| Delivery guarded by one boolean | A mis-set flag mails real recipients | Layered: `enabled` + `--send` + test mode default + live-mode environment confirmation + allowed domains + ledger. |

## Insufficient evidence

`evidence/daily-reporting/VALIDATION.md` is a LAB run of the HTML/JSON report against a five-host scope with seven API calls; it proves the
RC2 contract, not behaviour at scale, truncation, weekly/monthly windows, or any PDF/XLSX output. The native PDF path was prerequisite-blocked in the LAB.

## What was deliberately not rewritten

`bin/zabbix_daily_report.py`, `native_*.py`, the RC2 service/timer, the native-config handling and rollback, the `report.json` schema, the
installer's output keys (`CONFIG=PRESERVED`, `SECRETS=PRESERVED`, `TIMER_SCHEDULE=`...), and the report file names `daily-network-health-*.json|html`
in `report.output_directory`. The suite writes to a separate directory (`suite/`), so the two cannot overwrite or prune each other.

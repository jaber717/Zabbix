# Test plan and results

Nothing below was run against a production system, and **no live Zabbix validation of the suite has been performed**. The collector is tested against a
deterministic in-memory Zabbix API (`tests/reporting-suite/fakezbx.py`); whether the real 7.0.30 API behaves identically for every call is the first item of the
Codex validation (see HANDOFF-TO-CODEX.md).

## Results (this branch)

| Suite | Interpreter / host | Result |
|---|---|---|
| `tests/reporting-suite/test_*.py` (184 tests) | CPython 3.12.3, Ubuntu 24.04 (test VM), real wheels present | 184 / 184 PASS |
| same | **CPython 3.9.13** (the RHEL 9 interpreter version), Windows embeddable, ReportLab 4.2.5 / openpyxl 3.1.5 / Pillow 10.4.0 | 184 run, 182 PASS, 2 skipped (POSIX permission-bit tests) |
| `tests/reporting-suite/installer_suite_test.sh` | isolated root as root, bash on the test VM, RC2 tree supplied | PASS (12 checks: fresh install, verify+selftest, idempotent reinstall, vendor preserved, tampered wheel refused, missing lock refused, invalid config/timer mismatch, rollback, wrong-ABI wheels refused, upgrade from RC2, rollback to RC2) |
| RC2 baseline `tests/daily-reporting/` (static 4, unit 6, `installer_smoke.sh`, `native_rollback_test.sh`) | same VM | all PASS (unchanged tests, extended tree) |
| `scripts/build_offline_bundle.sh` → bundle verified on the VM | | checksum OK; preflight with the **real** lock and wheels `SUITE_WHEELHOUSE=PASS`; install of the cp39 wheels on Python 3.12 correctly refused |

Not run: a real RHEL 9 install (the real cp39 manylinux wheels were hash-verified and layout-checked but could not be imported here), `shellcheck` (not available), any live Zabbix.

## What each file proves

| File | Tests | Covers |
|---|---:|---|
| `test_periods.py` | 12 | half-open windows, adjacent periods share no second, ISO week (Mon/Sun), month lengths incl. leap year, **year rollover** (Dec→Jan, ISO week-year), previous-complete at the exact boundary and with a UTC `now`, DST day lengths (23 h / 25 h / 7×24 h−1 h), preceding period |
| `test_incidents.py` | 16 | resolved/started-before/open/resolved-after, boundaries, **duplicates**, **multi-host**, unreadable recovery, downtime class, deterministic order, **overlapping** incidents merged, per-host downtime, MTTR rules |
| `test_collector.py` | 27 | **targeted** `item.get` only (never without hostids/search, never `lastvalue`), requested kinds only, interface-tag filter, history vs trend choice, query bounds, batching at 160 extra hosts; statistics (**absent = None**, coverage unknown, raw vs hourly percentile, overflow, trend weighting, reboot detection, local-day buckets); **truncation** detection/splitting/remaining-truncation reporting, failed-batch isolation, **retries** on timeout/429/503, fail-fast on 403/API error, TLS verification on |
| `test_reports.py` | 49 | hand-computed KPIs/tables for all **six reports** (daily/weekly/monthly windows), **missing interface capacity**, N/A vs zero, **empty periods**, **year-rollover month**, SLA withheld when confidence is low, unresolved WAN links, group filter, Excel-header uniqueness, determinism and hash sensitivity |
| `test_renderers.py` | 22 | **PDF/XLSX/JSON reconciliation** (every KPI display string in the PDF text; every table cell and KPI value in the XLSX; JSON equals the document; the same dataset hash in all three), no formulas/macros, formula-injection strings stay text, freeze panes / tables / conditional formats / charts / number formats, warning box, row-limit notice, deterministic PDF bytes, non-Latin and markup characters, empty reports |
| `test_cli.py` | 37 | plan without API, all six reports × three formats, manifest checksums and **0640/0750** permissions, files-on-disk reconciliation, no secret in any output, **idempotent rerun** (inode/mtime unchanged), force, changed-data regeneration, corrupt-file regeneration, **atomic write failure** leaves no partial file and no manifest, one failing report does not stop the others, connection failure, **dry-run writes nothing**, fixture re-render, **retention** only for suite-made runs and never the run just made, **delivery matrix** (default off, `--send` without enable, `--no-email` wins, test-mode recipients only, live needs env + allowed domains, idempotent ledger, resend, changed report re-sent, SMTP failure not recorded, attachment size cap), existing output directories never chmod-ed |
| `test_packaging.py` | 21 | `suite.example.json` equals defaults, VERSION agreement, delivery off by default, 22 invalid-configuration cases, OnCalendar rendering, units/hardening, installer never enables timers or touches SELinux/firewall/GPG/TLS settings, suite code never touches `zabbix_server.conf`, **wheel lock pins** (hash format, official index, cp39/x86_64/manylinux), **real wheels match the lock**, safe zip members, self-test, no credentials, Python 3.9 syntax |
| `installer_suite_test.sh` | 12 steps | offline dependency installation, idempotency, tamper/ABI refusal, schedule rendering and mismatch detection, rollback, **upgrade from RC2 and rollback to RC2** (configuration, secrets, timer and generated reports preserved byte-for-byte) |

## Required scenarios → where covered

All six report types ✓ · daily/weekly/monthly windows ✓ · month/year rollover ✓ · open/resolved/overlapping incidents ✓ · duplicate and multi-host events ✓ · empty/missing/stale metrics ✓ ·
missing interface capacity ✓ · API truncation ✓ · rate-limit/timeout failures ✓ · PDF/XLSX/JSON reconciliation ✓ · offline dependency installation ✓ · upgrade compatibility and rollback ✓.

## How to run

```bash
# 1. wheels (connected workstation), then the Python tests
bash scripts/fetch_reporting_wheels.sh
mkdir -p /tmp/zrs-vendor && for w in reporting/daily-reporting/wheelhouse/*.whl; do python3 -c "import zipfile,sys;zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$w" /tmp/zrs-vendor; done   # on RHEL 9 (cp39 wheels)
ZRS_VENDOR=/tmp/zrs-vendor python3 -m unittest discover -s tests/reporting-suite -p 'test_*.py'

# 2. installer / upgrade / rollback in an isolated root (needs root; RC2_TREE is optional but required for the upgrade section)
mkdir /tmp/rc2 && git archive daily-reporting-v1.0.0-rc2 | tar -x -C /tmp/rc2        # on Linux, so files are LF
sudo RC2_TREE=/tmp/rc2 bash tests/reporting-suite/installer_suite_test.sh

# 3. RC2 baseline
sudo bash tests/daily-reporting/installer_smoke.sh && sudo bash tests/daily-reporting/native_rollback_test.sh
python3 -m unittest discover -s tests/daily-reporting -p '*test*.py'
```
On a non-3.9 Python the ABI-specific wheel (Pillow) must be replaced by a matching one for the full-install section; the script then also verifies that the real cp39 wheels are *refused*.

## Known gaps in the automated evidence

* No live Zabbix: API parameter shapes (`item.get` search/tags, `trend.get`, `history.get`, `event.get selectHosts`, `problem.get`) follow the 7.0 documentation; the fake
  rejects `selectHosts` on `problem.get` to mirror it, but only a live run can confirm every call.
* No RHEL 9 run: Python 3.9 compatibility is proven on a 3.9.13 interpreter, not on RHEL's build; the cp39 manylinux wheels are verified by hash/layout only.
* PDF appearance was reviewed by rasterizing samples, not by an automated visual test; XLSX was verified structurally with openpyxl, not opened in Excel.
* Scale: collection limits are exercised with small limits; no run with thousands of devices.

# Hand-off to Codex - Zabbix Reporting Suite (PDF / XLSX / JSON)

| | |
|---|---|
| Branch | `claude/reporting-suite-v1` (from the RC2 baseline; not merged anywhere) |
| Baseline | tag `daily-reporting-v1.0.0-rc2`, SHA `2fb5f19a2e8611e7f241f70ed1eb9b95a1d537bc` |
| Current SHA | the tip of the branch (`git rev-parse claude/reporting-suite-v1`); the last implementation commit is listed in the final message of the session; commits after it only touch this hand-off and the checksum manifest |
| Version | `1.1.0-rc1` (`reporting/daily-reporting/VERSION`, `zrs.SUITE_VERSION`) |
| Status | Implemented and tested **offline only**. No live Zabbix, no RHEL 9, no production, no email, no scheduling was used or enabled. |

## Changed files (53 vs baseline: 43 added, 10 modified)

* **New** `reporting/daily-reporting/lib/zrs/` (periods, apiclient, metrics, collector, plans, incidents, reports, model, render_json/pdf/xlsx, output, delivery, config, cli, `data/selftest.json`), `bin/zabbix_report_suite.py`,
  `config/suite.example.json`, `systemd/zabbix-report-suite@.service` + three timers, `wheels.lock`, `.gitignore`.
* **New** `scripts/fetch_reporting_wheels.sh`, `scripts/make_reporting_release_manifest.sh`; **new** `docs/reporting-suite/*`; **new** `tests/reporting-suite/*` (7 Python modules, fake Zabbix, installer test).
* **Modified** `scripts/{install,verify,rollback}_daily_reporting.sh`, `scripts/lib/daily-reporting-common.sh`, `scripts/build_offline_bundle.sh`, `scripts/daily-reporting-release.sha256`,
  `reporting/daily-reporting/{VERSION,DEPENDENCIES.txt}`, `docs/DAILY-REPORTING.md` (pointer + version), `.gitattributes` (LF for runtime files).
* **Unchanged on purpose**: `bin/zabbix_daily_report.py`, `native_*.py`, RC2 service/timer, `report.example.json`, Network Availability / Utilization / Device Health, alert automation, Zabbix server configuration.

## Implemented

Six reports - Daily Network Health (daily), WAN & ISP Performance, Infrastructure Health, Incident Analysis, Monitoring Quality (weekly), Executive Summary (monthly) - each as PDF, XLSX and JSON from one document;
period engine; targeted batched collection with truncation detection; coverage/confidence; incident reconstruction; atomic outputs, manifest + checksums, idempotent reruns, retention;
guarded e-mail (off by default); `--plan`, `--dry-run`, `--no-email`, `--fixture`, `--selftest`, `--cadence`; offline dependency packaging; installer/verifier/rollback integration; RC2 upgrade/rollback.
Details: [ARCHITECTURE.md](ARCHITECTURE.md), [KPI-DEFINITIONS.md](KPI-DEFINITIONS.md), [BASELINE-AUDIT.md](BASELINE-AUDIT.md).

## Tests (see [TEST-PLAN.md](TEST-PLAN.md))

184 Python tests: 184 PASS on CPython 3.12.3 (Linux) and 182 PASS + 2 POSIX-permission skips on CPython 3.9.13 (Windows). Installer/upgrade/rollback shell test (12 steps) PASS as root in an isolated root on Ubuntu 24.04.
RC2 baseline tests PASS against the extended tree. Offline bundle built, checksum verified, real-lock preflight PASS; wrong-ABI install refused.

## Dependencies

ReportLab 4.2.5, openpyxl 3.1.5, et_xmlfile 2.0.0, Pillow 10.4.0 (cp39 manylinux2014 x86_64), charset-normalizer 3.4.0 (cp39 manylinux2014 x86_64); pinned by SHA-256 in `wheels.lock`, shipped in the bundle,
installed offline into `<app>/vendor` (no pip, no repo changes, SELinux/firewalld/TLS/GPG settings untouched). Pillow is required by ReportLab at import time.

## Limitations (honest list)

1. **No live validation.** API call shapes follow the Zabbix 7.0 documentation and a fake that mirrors known restrictions (`problem.get` rejects `selectHosts`); real behaviour is unproven.
2. **Interface identity** comes from the `interface` item tag and key families (`net.if.in[`, `net.if.out[`, `net.if.status[`, `net.if.speed[`, `net.if.in.errors[`...) of the stock Cisco IOS by SNMP template; other templates may need `KEY_RULES` additions in `collector.py`.
3. **WAN links must be declared** in `suite.json` (`wan.links`); the ISP mapping is not derivable from Zabbix. An empty list yields an empty WAN report and N/A KPIs.
4. **Site mapping** uses the host tag named by `scope.site_tag` (default `site`), else the first host group; the LAB hosts' tags are unknown to me.
5. **Hourly granularity**: weekly/monthly utilization peaks and percentiles come from hourly trends and are labelled so; true 5-minute percentiles exist only for periods read from raw history (not used by any scheduled report).
6. **Downtime** is reconstructed from problem names matching `classification.downtime_problem_patterns` (RC2 setting); maintenance/suppressed periods are not subtracted.
7. Incidents older than `incident.lookback_days` (30) that ended inside the period are not seen (still-open problems of any age are).
8. PDFs use the built-in Helvetica family: non-Latin host names render as placeholder glyphs (no crash). Output was reviewed by rasterizing samples; XLSX was verified structurally, not in Excel.
9. Python 3.9 compatibility is proven on 3.9.13 (Windows), not on RHEL's build; the cp39 manylinux wheels are hash/layout-verified here but could not be imported here.
10. Scale (thousands of devices) is untested; limits are configurable and truncation is reported rather than hidden.
11. No `shellcheck`; bash parsed with `bash -n` and exercised by the isolated-root tests.

## Safe validation steps for Codex (LAB only; read-only against Zabbix; no mail, no timers)

```bash
git fetch origin && git switch claude/reporting-suite-v1
bash scripts/fetch_reporting_wheels.sh                              # connected workstation: downloads + verifies the wheels
# on the RHEL 9.6 LAB (python3 = 3.9): run the offline tests with the real cp39 wheels
mkdir -p /tmp/zrs-vendor && for w in reporting/daily-reporting/wheelhouse/*.whl; do python3 -c "import zipfile,sys;zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$w" /tmp/zrs-vendor; done
ZRS_VENDOR=/tmp/zrs-vendor python3 -m unittest discover -s tests/reporting-suite -p 'test_*.py'          # expect 184 OK
mkdir /tmp/rc2 && git archive daily-reporting-v1.0.0-rc2 | tar -x -C /tmp/rc2
sudo WHEELHOUSE="$PWD/reporting/daily-reporting/wheelhouse" RC2_TREE=/tmp/rc2 bash tests/reporting-suite/installer_suite_test.sh   # real wheels, real python 3.9 import check
```
Then, still without scheduling or e-mail, with the LAB credential in `ZABBIX_API_TOKEN` and the LAB `report.json`:
```bash
S=reporting/daily-reporting; export ZRS_VENDOR=/tmp/zrs-vendor
python3 $S/bin/zabbix_report_suite.py --config /etc/zabbix-daily-reporting/report.json --suite-config $S/config/suite.example.json --plan
python3 $S/bin/zabbix_report_suite.py --config ... --suite-config ... --report daily --dry-run          # KPIs only; compare with the Zabbix frontend
python3 $S/bin/zabbix_report_suite.py --config ... --suite-config ... --report all --no-email --output-directory /tmp/zrs-out
```
Check: (a) every call succeeds on 7.0.30 and `audit.api_by_method` / truncation lists look right; (b) device counts and availability agree with the frontend for the same period; (c) incident list agrees with Monitoring → Problems history;
(d) declare the 18 LAB P2P links in a copy of `suite.json` and confirm interface items resolve (the report lists any that do not); (e) open each XLSX in Excel/LibreOffice and each PDF in a viewer; (f) `python3 $S/bin/zabbix_report_suite.py --selftest`.
Do not set `delivery.enabled`, do not use `--send`, do not run the installer on the LAB with `--enable-suite-timers` until (a)-(e) are reviewed.

## Exact known blockers

* A write-free but **credentialed** LAB run is needed to validate the real API behaviour (item tags/keys on the 7 PNET hosts, `site` tag presence, trend retention for the chosen weeks).
* A **RHEL 9 host** is needed to prove the cp39 wheels import there (the installer will refuse the install otherwise - by design).
* **Recipients/SMTP** for live delivery are intentionally unconfigured; nothing can be sent until an operator sets `delivery.*`, `--send`, and (for live mode) `ZRS_ALLOW_LIVE_DELIVERY=YES`.
* Operator decision: the SLA target (`sla.target_percent`, default 99.9) and the downtime-class patterns need business confirmation before the monthly Executive Summary is circulated.

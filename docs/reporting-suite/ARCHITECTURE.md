# Reporting suite architecture

Version `1.1.0-rc1`, built on `daily-reporting-v1.0.0-rc2`. See [BASELINE-AUDIT.md](BASELINE-AUDIT.md) for what was reused and why.

```text
Zabbix 7.0 API ──► collector (targeted, batched, truncation-aware) ──► dataset (normalized, hashed)
                                                                           │
                                         reports.py (pure functions) ◄─────┘
                                                   │  ONE report document
                              ┌────────────────────┼─────────────────────┐
                         render_pdf (ReportLab)  render_xlsx (openpyxl)  render_json
                              └────────────────────┼─────────────────────┘
                              output.py: atomic write · manifest.json (SHA-256) · idempotency · retention
                                                   │
                              delivery.py (off by default, guarded, idempotent ledger)
```

## Source map (`reporting/daily-reporting/lib/zrs/`)

| Module | Responsibility |
|---|---|
| `periods.py` | Half-open `[start, end)` windows on local calendar days: daily, ISO-week (Monday or Sunday start), month; previous-complete and preceding-period logic; month/year rollover; DST-exact lengths. Zabbix `time_till` is inclusive, so queries use `end_ts - 1`. |
| `apiclient.py` | TLS-verified JSON-RPC client with retries on timeouts/connection errors/HTTP 429/5xx; `get_limited` (limit+1 truncation detection), chunked fetch, `fetch_time_split` (halves a window until it fits). `Notes` collects truncation and failures. |
| `metrics.py` | `Agg` accumulators and `fetch_history` / `fetch_trends` (split by item batch, then by time). Coverage = samples present / expected from the item interval. Hourly percentiles are named `p95_of_hourly_avg`. |
| `collector.py` | Host load and site mapping, **targeted** `item.get` (only needed key families, only given hosts, interface-tag filter), `attach_stats`, incident loading. |
| `plans.py` | What each of the six reports collects; WAN link resolution (declared links only). |
| `incidents.py` | De-duplication, clipping to the window, open/unknown-recovery handling, merged per-host downtime, MTTR. |
| `reports.py` | Dataset → report document, one pure builder per report; KPI formulas in `FORMULAS`. |
| `model.py` | Document model (KPIs, typed columns, tables, charts, dictionary, audit) and shared number formatting. |
| `render_*.py` | JSON, PDF, XLSX views of the same document. |
| `output.py` / `delivery.py` / `config.py` / `cli.py` | Files, mail, configuration, command line. |

## One dataset, three formats

The collector produces a normalized dataset and its SHA-256 (content only: the clock and API counters are excluded). `reports.build()` turns it into
a document of KPIs, typed tables and chart definitions. PDF, XLSX and JSON are rendered from that document only; the dataset hash is printed in the PDF
footer and metadata, in the XLSX Summary/Audit sheets, in the JSON and in the manifest. Tests render each report in all three formats and reconcile every KPI and
table value.

## Data honesty rules (enforced by code and tests)

* No value is invented: missing → `null`/`N/A`, never `0`; N/A is not "healthy".
* `lastvalue` is never read (a test greps the sources); history/trend only.
* A percentile from hourly trends is labelled `P95 (hourly avg)`; a raw `P95` exists only for periods read from raw history.
* SLA/availability confidence: HIGH ≥ 95 % sample coverage, MEDIUM ≥ 80 %, LOW below, NONE without samples, UNKNOWN when the interval cannot be derived.
  The SLA KPI is shown only if at least half of the devices have HIGH/MEDIUM confidence; otherwise N/A with the reason.
* Truncation, failed batches and unreadable recoveries appear in the report ("INCOMPLETE OR DEGRADED DATA"), the audit sheet and the e-mail body.

## Interaction with Zabbix

Read-only API methods: `apiinfo.version`, `host.get`, `item.get`, `trend.get`, `history.get`, `event.get`, `problem.get`. Nothing is written to Zabbix;
`zabbix_server.conf` is never read or changed by the suite. Authentication reuses `ZABBIX_API_TOKEN` (or user/password) from `secrets.env`.

## Platform integration

* Application `/opt/zabbix-daily-reporting` (code + `vendor/` for the offline-installed ReportLab, openpyxl, et_xmlfile, Pillow, charset-normalizer).
* `/etc/zabbix-daily-reporting/report.json` (RC2 contract, unchanged) and `suite.json` (new; preserved on upgrade; see `config/suite.example.json`).
* Outputs `/var/lib/zabbix-daily-reporting/suite/<report>/<period>/` with `*.pdf *.xlsx *.json manifest.json` (files `0640`, directories `0750`), delivery ledger beside them.
* systemd: `zabbix-report-suite@.service` (oneshot, hardened, `--cadence %i`) and `zabbix-report-suite-{daily,weekly,monthly}.timer`, installed **disabled**.
* Offline dependencies: `wheels.lock` pins five wheels (RHEL 9 = CPython 3.9, x86_64) by SHA-256; `scripts/fetch_reporting_wheels.sh` (connected workstation) downloads and
  verifies them; the bundle carries them; the installer re-verifies, extracts into `vendor/` *before* the application swap, and runs `--selftest` on the staged copy
  (refusing wrong-ABI or tampered wheels). No pip, no network, no `--nogpgcheck`/`sslverify` changes. SELinux, firewalld and the Zabbix server configuration are not touched.
  PyPI wheels carry no GPG signatures; integrity rests on the pinned SHA-256 values and the bundle checksum.

## Safeguards

| Risk | Control |
|---|---|
| Mail to real recipients | Off by default. Needs `delivery.enabled` **and** `--send`; recipients are `test_recipients` unless `mode: live` **and** `ZRS_ALLOW_LIVE_DELIVERY=YES` **and** every recipient in `allowed_recipient_domains`. `--no-email` always wins; `--dry-run` never sends. |
| Duplicate mail | Ledger keyed by report, period, dataset hash, recipients and attachment hashes; `--resend` overrides. |
| Partial files | Temp file + fsync + chmod + rename; manifest written last (no manifest = incomplete run). |
| Rewriting identical reports | A run whose manifest dataset hash and file checksums match is `UNCHANGED`. |
| Disk growth | Per-cadence retention that deletes only runs it created, never the run just made. |
| Surprise scheduling | Timers installed disabled; `--enable-suite-timers` is explicit and refuses without credentials. |

## Operations

```bash
python3 /opt/zabbix-daily-reporting/bin/zabbix_report_suite.py --config /etc/zabbix-daily-reporting/report.json \
        --suite-config /etc/zabbix-daily-reporting/suite.json --plan            # periods only, no API
... --report daily --dry-run                                                       # reads Zabbix, prints KPIs, writes nothing
... --report all --no-email                                                        # generate everything, never mail
... --selftest                                                                      # no Zabbix: renders a synthetic dataset
```
Reports: `daily` `wan` `infra` `executive` `incident` `quality` (or `all`); `--cadence daily|weekly|monthly` is what the timers use; `--date YYYY-MM-DD` selects
the period containing that date; `--formats pdf,xlsx,json`; `--fixture dataset.json` re-renders a saved dataset (the JSON output embeds it) without Zabbix.

WAN reports need the links declared in `suite.json` (`wan.links`: host, interface as in the item tag `interface`, ISP, optional site and `capacity_bps`) because the ISP
mapping cannot be derived from Zabbix. Undeclared/unfound links are listed in the report, never guessed.

Native Zabbix scheduled PDF reporting (RC2) remains optional and independent; the custom renderer needs neither `zabbix-web-service` nor a browser.

# Integration with the automated PDF / Excel reporting suite

The reporting suite (branch `claude/reporting-suite-v1`, v1.1.0-rc1) already owns rendering, e-mail delivery, scheduling, archiving and the document model. This project **does not duplicate any of that**. It supplies SLA content only.

## Contract

`./sla.sh --env <env> report --month YYYY-MM --out sla.json --suite-doc doc.json`

| File | Schema | Consumer |
|---|---|---|
| `sla.json` | `zabbix-sla-report-v1` (services with SLI, SLO, state, error budget, burn rate, coverage, signal quality, caveats, evidence tier; link-signal quality; planned downtime; provider-claim note; warnings) | machines, audit |
| `doc.json` | `zabbix-reporting-suite-report-v1` (`report: "sla"`; kpis, findings, three sections/tables, dictionary, warnings, audit) | the suite's renderers |

The document is built with the same shape the suite's own reports use (`kpis`, `findings`, `sections`, `tables` with typed `columns`, `dictionary`, `warnings`, `audit`, `dataset_sha256`). Tests pin that shape (`tests/test_reporting.py::TestBridge`). Percent columns hold percent values; an `INSUFFICIENT_DATA` service has `sli = null`, which every renderer prints as `N/A`.

## What the suite needs (one small change, on its side)

The suite renders from a dataset it collects itself. To render a document supplied by another tool it needs an entry such as:

```text
zrs --document doc.json --formats pdf,xlsx,json --output-directory <dir>     # skip collection; run the existing renderers on the document
```

Estimated size: ~20 lines in `lib/zrs/cli.py` (load JSON, check `schema == zabbix-reporting-suite-report-v1`, call `render_json/render_pdf/render_xlsx`, and the existing delivery code). Two cosmetic additions improve the PDF/XLSX: add `COMPLIANT`, `BREACHED`, `INSUFFICIENT_DATA` to its `CELL_STATUS` / `STATUS_FILL` colour maps. That change belongs to the reporting project and is intentionally **not** made here (no edits to the other branch, no duplicated renderer). Until it exists, `doc.json` is already a valid JSON deliverable and `sla.json` can be read by anything.

Scheduling and e-mail for the SLA report are configured in the suite and are out of scope until approved.

## Why a document and not a copy of the KPIs

The suite's `quality` and `executive` reports compute *device* availability from raw Zabbix history. The SLA report is the *service* view from Zabbix's own SLA engine, qualified by monitoring-data quality. Different questions, different numbers; the document keeps them separate and the dictionary says so. Provider contractual SLAs appear in neither.

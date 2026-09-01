# M4 Resumption Dry-Run

Date: 2026-09-01

The deployed `netbox-zabbix-sync` service was run in its immutable dry-run mode
after permission revalidation. The service exited 3, its designed blocked-gate
result. The timer remains enabled and active.

## Observed plan

| Measure | Result |
|---|---:|
| Readable devices | 81 |
| Readable DCIM interfaces | 1105 |
| Readable IP addresses | 116 |
| Virtual machines | UNKNOWN (HTTP 403) |
| VM interfaces | UNKNOWN (HTTP 403) |
| Tags | UNKNOWN (HTTP 403) |
| Custom fields | UNKNOWN (HTTP 403) |
| Resolved mappings | 24 |
| Unmapped records | 57 |
| Eligibility unknown due to permission | 81 |
| Missing or unsafe management IP | 41 |
| Actionable candidates | 0 |
| Proposed creates | 0 |
| Proposed updates | 0 |
| Orphans | UNKNOWN (incomplete source) |
| Change ratio / budget | 0.0 / 0.1 |

The change-budget calculation passes, but that does not authorize apply: the
required-NetBox-read and candidate-resolution gates are blocked. Because tags
and custom fields cannot be read, the evidence cannot support individual
eligibility decisions. None of the 81 readable devices is classified as
eligible or ineligible; every decision remains `UNKNOWN`.

`apply_result.status=NOT_EXECUTED`. A least-privilege Zabbix apply credential
was not created because source completeness is a prior hard gate. No apply or
post-apply second reconciliation ran.

Raw report: `raw/dry-run-after-permission-change.json`.

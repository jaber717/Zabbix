# M4 Live Plan Review

## Source and candidate inventory

| Measure | Actual result |
|---|---:|
| Physical devices | 81 |
| Virtual machines | 0 |
| VM interfaces | 0 |
| Eligible | 0 |
| Ineligible | 81 |
| Eligibility unknown | 0 |
| Mapped | 24 |
| Unmapped | 57 |
| Ambiguous | 0 |
| Needs review | 0 |
| Missing management IP | 41 |
| Duplicate management IP | 0 |
| Proposed creates | 0 |
| Proposed updates | 0 |
| Unchanged | 0 |
| Orphan candidates | 0 |
| Template drift | 0 |

Every candidate is deterministically ineligible with reason `not_opted_in`:
the source contains no `monitoring-enabled` tag and no device has a truthy
`monitoring_enabled` custom-field value. The 81-record identity/reason ledger is
in `raw/candidate-reasons.jsonl`.

Primary-IP resolution succeeded for 40 records and deterministically identified
41 missing primary IPs. Mapping resolved 24 records and left 57 unmapped. These
facts do not block this plan because none of those records is opted in; an
eligible record with unresolved mapping or IP state would fail closed.

All 81 candidate identities are unique, no duplicate management IP exists, and
an independent rebuild produced the same candidate ledger. Required reads,
candidate resolution, duplicate identity, mapping targets, orphan evaluation,
destructive safeguards, the scoped credential, and the 10% budget all passed.
The modification ratio was 0.0.

# M4 Actual Runtime Dry-Run

The installed `nbzsync` service ran twice against authoritative NetBox
`192.168.1.89` and Zabbix `192.168.1.91`. Both aggregate reports are
byte-identical with SHA256
`8807545aa7bca17e1a2d0833dd55386cab8f4e10ed99a03b36d0086a326fd049`.

| Metric | Result |
|---|---:|
| NetBox devices readable | 81 |
| NetBox VMs readable | UNKNOWN (HTTP 403) |
| DCIM interfaces readable | 1105 |
| VM interfaces readable | UNKNOWN (HTTP 403) |
| IP addresses readable | 116 |
| Eligibility known | 0 |
| Eligibility UNKNOWN due permission | 81 devices; VM population UNKNOWN |
| Mapping-resolved device records | 24 |
| Unmapped device records | 57 |
| Missing/unsafe primary IP | 41 |
| Duplicate primary IP conflicts | 0 observed among readable objects |
| Proposed creates | 0 |
| Proposed updates | 0 |
| Unchanged managed hosts | 0 |
| Orphan candidates | UNKNOWN; evaluation blocked by incomplete source |
| Apply | NOT-EXECUTED |

The reports show `required_netbox_reads=BLOCKED`,
`candidate_resolution=BLOCKED`, and `zabbix_credential_scope=BLOCKED`.
Modification ratio was 0.0 against a 0.10 budget. The service deliberately
exited 3, leaving the timer enabled/active/waiting and exposing the blocked
condition rather than reporting success.

Evidence: `raw/dry-run-1.json`, `raw/dry-run-2.json`,
`raw/dry-run-determinism.txt`, `raw/dry-run-journal.txt`, and
`raw/service-timer.txt`.

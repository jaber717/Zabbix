# zabbix-sla - Zabbix Enterprise SLA & Service Assurance

YAML-first, native-Zabbix (7.0) service and SLA platform. It measures **service availability** (is a site able to reach what it needs?) instead of only device uptime, models redundant paths correctly, and reports monthly SLI / SLO / error budget with explicit data-quality qualification.

**Status: LAB implementation, offline-tested (131 tests). NOT production-ready - independent live acceptance pending** (see [docs/HANDOFF-TO-CODEX.md](docs/HANDOFF-TO-CODEX.md)).

Independent of `../zabbix-alerting` (NETOPS Interface Alerting v1.0.1), which it reuses by import - its environment-identity guard, API client and strict YAML loader - without modifying it.

```bash
cp config/.env.example .env            # LAB URL + token, never committed
./sla.sh --env lab check               # validate the inventory (offline)
./sla.sh --env lab plan                # what would change (read-only)
./sla.sh --env lab apply               # backup, write, readback-verify
./sla.sh --env lab verify              # semantic drift (exit 2 = drift)
./sla.sh --env lab rollback --backup state/backups/<file>.json
./sla.sh --env lab quality | report --month YYYY-MM | simulate --down <link_id> | dashboards plan
python3 -m unittest discover -s tests -t .          # offline suite
```

| Read this | For |
|---|---|
| [docs/HLD.md](docs/HLD.md) | architecture proposal, semantics, tiers, tag taxonomy |
| [docs/PHASED-PLAN.md](docs/PHASED-PLAN.md) | phases and gates |
| [docs/EVIDENCE-REQUESTS.md](docs/EVIDENCE-REQUESTS.md) | unknowns and the evidence required |
| [docs/LLD.md](docs/LLD.md) | modules, objects, algorithms, failure behaviour |
| [docs/OPERATOR-GUIDE.md](docs/OPERATOR-GUIDE.md) | day-to-day use |
| [docs/ACCEPTANCE-MATRIX.md](docs/ACCEPTANCE-MATRIX.md) | live acceptance A-01..A-25 |
| [docs/INTEGRATION-REPORTING.md](docs/INTEGRATION-REPORTING.md) | hand-off to the PDF/Excel reporting suite |
| [docs/PRODUCTION-RUNBOOK.md](docs/PRODUCTION-RUNBOOK.md) | attended production rollout (do not start before acceptance) |
| [docs/HANDOFF-TO-CODEX.md](docs/HANDOFF-TO-CODEX.md) | what to run, limitations, what to send back |

Layout: `slaas/` code · `inventory/{lab,production}.yaml` · `config/environments/` · `dashboards/` · `scripts/` (tag audit, live acceptance helpers) · `tests/` · `evidence/` · `state/` (backups/journals, Git-ignored).

Principles: utilization is never downtime · missing data is never 100 % · redundancy is modelled, not assumed · provider SLA claims are separate from our measurements · no production change or scheduling without approval · no credentials in Git · no direct database access.

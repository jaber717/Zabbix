# Phased implementation plan

Gate rule: a phase is "done" only when its automated tests pass **and** (for live phases) Codex's acceptance evidence is attached. Nothing is called production-ready before Phase 6.

| Phase | Scope | Delivered here | Exit gate |
|---|---|---|---|
| 0 Discovery | Reuse analysis of `zabbix-alerting`; read-only tag audit; topology facts; unknowns list | **Done** (docs + `evidence/tag-audit-lab.json`) | Codex answers EVIDENCE-REQUESTS E-01..E-03 |
| 1 Engine (LAB, offline) | Inventory schema + strict validation; tag taxonomy; service/SLA compilation; env identity reuse; planner with semantic drift; apply with backup + readback; rollback; status evaluator (what-if); API model of `service.*`/`sla.*` | **Done, offline-tested** | `accept_tag_semantics.py` + `accept_api_shapes.py` pass live in LAB (Codex) |
| 2 Infrastructure + path services (LAB) | 11 link leaves, series paths, parallel connectivity, business services, SLA objects (SLO unapproved placeholders) | **Done as YAML + tested compile/plan/apply on the API model** | Live apply, readback, rollback in LAB (Codex); failure injection proves redundancy (A-05..A-08) |
| 3 Active Assurance | Probe schema, routing-proof rule, quorum, freshness, API creation of items/calculated item/triggers, probe signal services, quality services | **Done as definitions + generator + tests; probes `proposed`, not activated** | Codex supplies runners/destinations/routing proof (E-04..E-07) and runs probe acceptance (A-09..A-12) |
| 4 SLO / reporting | `sla.getsli` ingestion, qualification (coverage), burn rate, error budget, planned-downtime policy, monitoring-quality validation, reporting bridge document | **Done offline** | Real `sla.getsli` shape confirmed live (A-13); reporting suite renders the document (A-15) |
| 5 Dashboards | YAML dashboards (executive, NOC), generator, drift | **Spec + generator, apply gated** | Widget field types taken from a Codex-exported dashboard (E-10); provisioning acceptance (A-16) |
| 6 Production | Production inventory, runbook, approvals, scheduling | **Runbook only; inventory empty; nothing scheduled** | Explicit approval + Codex live acceptance of 1-5 |

## Order of live work for Codex (smallest blast radius first)
1. Read-only: answer E-01..E-03 (tag semantics can be tested later, but API shapes first).
2. LAB, write: `accept_tag_semantics.py`, `accept_api_shapes.py` (create/delete their own throw-away services).
3. LAB: `./sla.sh --env lab check`, `plan`, `apply`, `plan` (expect no changes), `verify`, failure injections, `rollback`.
4. Probes (after E-04..E-07), dashboards (after E-10), reporting integration.

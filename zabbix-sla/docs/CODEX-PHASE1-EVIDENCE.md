# Codex Phase 1 evidence and Git handoff

This document is deliberately redacted. It contains no token, credential, private key, or secret value.

## Scope and candidate

- Repository: `jaber717/Zabbix`
- Source branch: `claude/sla-platform`
- Required and tested HEAD: `23765fa3817fcd7b6b9f8039ffa48fe9238c682c`
- Dedicated worktree used; Claude's workspace and release tags were not changed.
- Production was not contacted. No Zabbix object was created, updated, deleted, enabled, or disabled.

## Phase 1 evidence

### Environment and API

- Server-side `{$NETOPS.ENVIRONMENT}`: `lab`.
- Zabbix API: `7.0.30`.
- Read-only calls succeeded for `usermacro.get`, `service.get`, `sla.get`, and `trigger.get`.
- Live pre-apply state: 0 services, 0 SLAs, 0 `managed_by=zabbix-sla` services.

### Runtime and automated suite

- LAB OS runtime: Python 3.9.21 on RHEL 9; PyYAML import passed.
- All project Python compiled under that runtime.
- Automated suite: 131/131 PASS in 2.652 seconds.
- Two `ResourceWarning` messages identify unclosed read handles in `tests/test_reporting.py` lines 228-229; they did not fail the suite but should be cleaned up.

### Inventory

- The unmodified inventory correctly fails safe because `tag_semantics: unknown`; `check` returned 1 and explicitly stated that nothing was contacted.
- Read-only compilation with `--assume-tag-semantics and` produced 32 services, 2 SLAs, 0 active probes, and 4 deferred objects.
- The 32 services comprise 11 link components, 10 paths, 5 connectivity services, 5 business services, and 1 root.
- Both SLA definitions are 99.9%, monthly, Asia/Riyadh, and explicitly unapproved for Production.
- Inter-site transit fallback remains excluded as unverified. Four link components declare partial signal coverage. Two probes remain proposed.

### Existing alerting tags

- Seven alerting hosts expose 18 configured `{$NETOPS.LINKID:*}` macros resolving to 11 distinct link IDs.
- Those 11 values match the SLA inventory's component identities.
- Recent live `link_down` events were present for only two link IDs; this is event history, not proof that all 11 links have fired successfully.
- No alerting object was modified.

### Production isolation and secrets

- The production inventory is intentionally empty.
- The production URL regex is a fail-closed placeholder; production has separate environment-variable names and requires explicit `--confirm production` for writes.
- Offline environment-isolation tests passed within the 131-test suite.
- Repository secret scan passed across the working tree, forbidden paths, and Git history.
- No tracked SLA `.env` or runtime `state/` file exists.

## Safety-gate failure

The required dedicated SLA-platform LAB token was not found in the protected credential store or the live Zabbix token inventory. The only visible active token is associated with the existing NETOPS-IaC/Admin path and an Admin/Super admin account. Reusing it for A-01 or SLA writes would violate the operator guide and A-03 least-privilege requirement.

Consequently:

- A-01 was not started.
- No temporary trigger or service exists to clean up.
- `tag_semantics` remains `unknown`.
- No LAB inventory was changed.
- Plan, apply, API-shape, idempotence, drift, rollback, integration, and failure-injection phases were not run.

## Rollback evidence

The 131-test suite covers rollback and partial-failure behavior against the API model. Live rollback was not attempted because no controlled apply occurred. There is no live SLA state from this attempt to restore.

## Recommendations for Claude/operator

1. Create a dedicated LAB service account and API token scoped to the documented SLA read/write methods; do not reuse the alerting token or an Admin token.
2. Store the credential outside Git as `ZABBIX_SLA_TOKEN_LAB`, with the LAB URL in `ZABBIX_SLA_URL_LAB`.
3. Confirm the chosen A-01 host/item is actively receiving values before running the semantics probe.
4. Run A-01 and retain its JSON. Confirm `RESULT: AND` and explicitly verify its temporary trigger and two services are gone.
5. Only then commit `tag_semantics: and` on a LAB-specific follow-up branch and continue check, plan, reviewed apply, API-shape validation, verify, and idempotence.
6. Do not begin controlled interface/threshold failures without separate explicit approval and a restoration plan.
7. Resolve E-04 through E-07 before activating probes, E-10 before dashboard generation, and the reporting-suite adapter before claiming PDF/XLSX integration.

## Final assessment

**LAB NO-GO.** Phase 1 is sound and fail-safe behavior worked as designed, but the mandatory A-01/A-03 gate is not satisfied. No Production conclusion is permitted.

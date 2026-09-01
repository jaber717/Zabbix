# Implementation Plan

M0, M0.5, and M1 are complete. M2 was explicitly authorized on 2026-09-01 and
is in progress. M3 has not started and is not authorized. Every milestone ends
with a stop/review gate.

## M0 — Discovery + Specifications

- **Scope:** Capability check, bounded read-only discovery, raw evidence, durable
  specifications, discovery report, plan, status, safety review, commit.
- **Inputs:** Approved architecture brief, accessible workspace, proven read-only
  access only.
- **Deliverables:** Six specs, `DISCOVERY.md`, capability/raw/required evidence,
  this plan, changelog, status, scaffold, commit.
- **Tests:** File presence, status-policy review, evidence traceability, forbidden
  operation scan, secret-pattern scan, Git review.
- **Permissions:** Local repository writes; remote GET/read-only commands only.
- **Risks:** Secret leakage, stale documentation mistaken for fact, accidental
  remote mutation, inferred PASS.
- **Stop condition:** Commit the M0 baseline and wait. Do not install or build.

### Gate dependency matrix

| Dependency | Affected milestone |
|---|---|
| Verified usable RHEL BaseOS/AppStream and official Zabbix 7.0 source | RESOLVED by M0.5; M1 COMPLETE |
| Pinned `fping` from the fping-only official Zabbix non-supported source | RESOLVED by M1; no broader source authorized |
| NetBox VM/tag/custom-field read permission | Blocks M4 |
| NetBox 6.0.8 versus portal 4.6.9 compatibility | Blocks/affects M4 and M6 |
| PNETLab/EVE availability | Prerequisite only for M8 |

## M0.5 — Build Source Readiness

- **Scope:** Capture pre-change state; enable only standard RHEL 9 BaseOS and
  AppStream; verify real modules/Python; verify official Zabbix 7.0.30 metadata;
  prove isolated clean-installroot source and dependency access.
- **Inputs:** Accepted M0 evidence, registered RHEL 9.6 x86_64 build VM,
  passwordless approved repository administration.
- **Deliverables:** Redacted pre/post repository evidence, module/Python source
  inventory, official Zabbix metadata/key/package evidence, clean-context proof,
  source decision, gate update, commit.
- **Tests:** All M0.5 acceptance items in `PROJECT-STATUS.md`.
- **Permissions:** Enable only BaseOS/AppStream; metadata/query operations;
  disposable clean-root state. No host package install or module change.
- **Risks:** Wrong source IDs, unintended repository influence, account identifier
  leakage, host RPM/module mutation, stale temporary state.
- **Stop condition:** Source readiness proven and committed. Do not start M1.
- **Result:** COMPLETE; M1 source gate READY.

## M1 — Offline Build Pipeline

- **State:** COMPLETE (2026-09-01); the official Zabbix non-supported RHEL 9
  source supplied only pinned `fping`. M2 was separately authorized afterward.
- **Scope:** Compatibility profile, clean installroot, RPM/module closure, Python
  wheels, artifact assembly, manifests, hashes, and build verification.
- **Inputs:** Completed RHEL build evidence; verified usable BaseOS/AppStream and
  all approved source repositories in the clean build context; approved
  versions/Python ABI and source policy; resolved M1 blockers.
- **Deliverables:** `compat/zabbix-7.0.yaml`, reproducible build automation,
  offline repository/wheelhouse, curated artifact builder and metadata.
- **Tests:** Clean buildroot closure; external repos disabled; module list/enable;
  GPG/hash checks; clean artifact extraction; lab/secret leakage tests.
- **Permissions:** Explicit build-VM and repository access; no target install.
- **Risks:** Incomplete modular metadata, host-state dependency, ABI mismatch,
  licensing/provenance gaps, artifact contamination.
- **Stop condition:** Reproducible verified build artifact; do not install it.
- **Prior stop:** The initial source set lacked `fping`; retained as evidence.
  The amended runs found no further missing dependency or source expansion.
- **Result:** Two fresh builds passed; 313-RPM closure, lock/provenance,
  signatures, modular metadata, local-only installations, artifact checks, nine
  negative tests, and meaningful reproducibility all passed.

## M2 — Installer

- **State:** IN-PROGRESS (authorized 2026-09-01); M3 is not authorized.

- **Scope:** Bootstrap/Ansible for PostgreSQL, Zabbix, nginx/PHP, TLS, SELinux,
  firewalld, systemd, backup, upgrade skeleton, and state model.
- **Inputs:** M1 artifact/profile; approved target configuration and certificates;
  installation safety decisions.
- **Deliverables:** Small bootstrap, Ansible roles/playbooks, release state,
  preflight, backup/restore/upgrade procedures.
- **Tests:** Syntax/lint; fresh disposable install; converge/check mode; database
  safety negatives; SELinux/firewalld/TLS; backup/restore dry validation.
- **Permissions:** Disposable test target only; no existing production database.
- **Risks:** Reinitialization, unsafe downgrade, hidden Internet dependency,
  SELinux workaround, non-idempotent services.
- **Stop condition:** Installer verified on disposable target; do not deploy lab.

## M3 — Zabbix Lab Deployment

- **Scope:** Provision/deploy dedicated `ZABBIX-01`; validate platform and
  self-monitoring.
- **Inputs:** Approved VM plan/resources/network values and M2 installer.
- **Deliverables:** Lab deployment, configuration inventory, operational and
  idempotency evidence.
- **Tests:** Install/converge, services/UI/API, database, Agent 2, TLS/firewall,
  SELinux Enforcing, reboot, backup/restore checkpoint, self-monitoring.
- **Permissions:** Explicit permission to create/change only `ZABBIX-01`.
- **Risks:** Network collision, resource pressure, downtime, certificate/secret
  mishandling.
- **Stop condition:** Stable dedicated lab instance; no NetBox integration.

## M4 — NetBox Integration

- **Scope:** Audit/fetch devices and VMs, identity, mapping/resolver, dry-run,
  guarded apply, lifecycle, service/timer, self-monitoring.
- **Inputs:** Resolved NetBox version/permission blockers, approved mappings,
  read-only NetBox and least-privilege Zabbix credentials.
- **Deliverables:** Tested sync service, configuration schema, reports, audit
  records, systemd units, runbook.
- **Tests:** Device+VM fixtures/live reads; duplicate PK/name; dry-run determinism;
  change breaker; forbidden delete/unlink; IP ambiguity; outage/credential errors;
  limited approved apply and convergence.
- **Permissions:** Read NetBox; Zabbix writes only after dry-run approval. No
  NetBox write.
- **Risks:** Mass change, incorrect identity, privilege excess, template/IP churn.
- **Stop condition:** Safe limited reconciliation demonstrated; no estate rollout.

## M5 — Real Monitoring

- **Scope:** Monitor Proxmox, existing guests, NetBox LXC, and approved services;
  tune initial alerts.
- **Inputs:** M3 platform, M4 integration, explicit endpoint credentials and
  network-flow approval.
- **Deliverables:** Real hosts/templates/checks, evidence, alert thresholds,
  operations notes.
- **Tests:** Genuine metrics, availability, CPU/RAM/disk/interfaces, service
  reachability, approved controlled failure/recovery, alert delivery.
- **Permissions:** Monitoring configuration only; no guest lifecycle change unless
  separately approved for a specific test.
- **Risks:** Load, alert noise, credential scope, disruption during failure tests.
- **Stop condition:** Stable useful monitoring; do not create mock NetBox data.

## M6 — Mock DCIM / Cabling

- **Scope:** Isolated NetBox mock estate, rack/cable/power/circuit cases, portal
  traversal contract if source remains available.
- **Inputs:** Approved mock tenant/site/tag naming and explicit NetBox write
  authorization; tested rollback/export plan.
- **Deliverables:** Idempotent mock fixture, expected topology/cabling outputs,
  portal contract tests.
- **Tests:** All SPEC-04 cable/power cases; far operational endpoint; broken path;
  planned/unracked/0U cases; sync exclusion; provenance.
- **Permissions:** Additive writes only inside isolated mock estate.
- **Risks:** Collision with real inventory, fictional semantics, incomplete cleanup.
- **Stop condition:** Fixture and portal behavior verified; no emulator work.

## M7 — Offline Release Candidate

- **Scope:** Fresh disconnected RHEL validation, restore/negative tests, corporate
  template/validator, artifact hygiene, release candidate.
- **Inputs:** M1–M6 deliverables, clean disconnected test system, corporate flow
  requirements and approved trust material.
- **Deliverables:** Signed/hashed RC artifact, manifests/build info, operational
  docs, template, readiness report and handover package.
- **Tests:** Fresh install, converge, reboot, backup/restore, negative paths,
  external-repo isolation, artifact secret/lab scan, portability without edits.
- **Permissions:** Disposable disconnected target and approved transfer staging.
- **Risks:** Environmental coupling, missing docs/recovery, scan rejection,
  non-reproducibility.
- **Stop condition:** Release-gate review; no corporate deployment.

## M8 — Phase 2 Observed Topology

- **Scope:** PNET/EVE, LLDP/CDP, optional snmpsim, vendor recordings, topology
  reconciliation, and Live HLD enhancements.
- **Inputs:** Explicit emulator access, sanitized lawful fixtures, provenance/data
  model, portal decision.
- **Deliverables:** Collectors/normalizers, observed store, reconciliation states,
  regression fixtures and views.
- **Tests:** Vendor local-port quirks; intended/observed separation; timestamp and
  stale behavior; match/mismatch/missing/discovered/ignored; outage behavior.
- **Permissions:** Emulator and simulator changes only; NetBox remains intended
  source and existing workloads remain protected.
- **Risks:** Vendor ambiguity, sensitive walk content, false drift, topology merge.
- **Stop condition:** Observed topology proven without corrupting intended state.

## M9 — Advanced Operations

- **Scope:** Evidence-driven redundancy-aware dependencies, proxies/proxy groups,
  HA, database split/HA, or TimescaleDB where justified.
- **Inputs:** Measured scale/availability bottlenecks, support policy, approved
  architecture change and migration/rollback plan.
- **Deliverables:** Architecture decision records, prototype, migration automation,
  operating model and capacity evidence.
- **Tests:** Failure domains, quorum/failover, data integrity, restore, performance,
  upgrade/rollback and operational burden.
- **Permissions:** Separate architecture and change approval for each capability.
- **Risks:** Complexity, split brain, unsupported combinations, recovery burden.
- **Stop condition:** Each advanced feature independently gated; default is no
  introduction without measured need.

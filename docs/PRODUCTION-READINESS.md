# RHEL 9.x targeted hardening

Policy: RHEL 9.x x86_64. Production RHEL 9.7 CONNECTED is not accessible and
has not been tested end to end. The available RHEL 9.6 lab is already installed;
its rerun is not a clean-machine test. TEST-EVIDENCE records earlier commits.

Privileged subscription release/identity discovery currently reports an
unregistered host; only the existing local offline repository is visible.
CONNECTED staging therefore lacks authorized BaseOS/AppStream access. This is
an environment limitation, not permission to register the host, change its
release setting, or enable/disable system repositories. Final execution results
and exact commit identity are supplied in the handover after this document is
committed. No success is implied by the planned checks below.

## Blocker audit

| Condition | Previous behavior | Final behavior | Classification | Evidence |
|---|---|---|---|---|
| OS minor/string | Exact minor in stage/build/bootstrap/Ansible/upgrade | Shared `installer/lib/platform.sh:validate_rhel_platform`; callers install, verify, stage, build, bootstrap, baseline, installed upgrade helper | FIX | `test_os_acceptance_matrix_and_caller_globals`, `test_os_release_is_never_evaluated`, `test_no_active_exact_minor_gate_or_forced_pin` |
| Release pin | Fixed flag and mandatory specific pin | Only successful numeric RHSM output is a pin; otherwise normal host DNF substitution; empty roots inherit it | FIX | `test_release_pin_parser`, `test_release_context_uses_host_dnf_without_pin`, `test_release_context_honors_real_pin_and_rejects_conflict` |
| RHSM identity and repo IDs | Local consumer identity and fixed IDs required | Actual content access required; optional runtime RHEL repo IDs | CONFIGURE | Stage makecache fails closed; live access currently BLOCKED |
| Historical OS lock | Full historical NEVRA equality in every build | CONNECTED generates its own exact dependency lock; frozen historical comparison remains explicit | FIX | `test_staging_controls_and_generated_lock`; new live resolution remains unverified |
| Application pins | Zabbix/fping versions, module streams | Preserved Zabbix 7.0.30, fping 5.1, PostgreSQL 16, PHP 8.3, nginx 1.24, Python ABI 3.11 | KEEP | Existing profile/lock tests and bundle fixture |
| Bundle content identity | Historical minor embedded | Concrete host minor recorded; downloaded redhat-release must match; effective repo release recorded | FIX | Static build assertions; live new artifact generation BLOCKED |
| Dependency closure | Empty source root, resolve/alldeps, empty local server/proxy roots | Existing implementation preserved | KEEP | Build source and staging-control regression; no new closure result claimed without sources |
| Stale external pointer | CONNECTED silently reused bundle-root | CONNECTED stages current clean source; explicit bundle selection only in AIRGAPPED; verify reads installed pointer | FIX | `test_connected_rejects_explicit_old_bundle`, staging-control regression |
| Airgap minor | One fixed bundle/host pair | Bundle/profile minor must match supported running host; integrity retained | FIX | `test_bundle_minor_mismatch_fails`; bootstrap/upgrade call `installer/lib/validate_bundle.py:validate` |
| Timezone | Only one region allowed | Installed IANA zone supplied at runtime | CONFIGURE | Runtime validation tests |
| Password transport | Late rejection in database role | Same character policy rejected before staging | FIX | Runtime input regression; no secret policy expansion |
| Root/secrets/TLS/SELinux/firewall | Mandatory protection | Preserved | KEEP | Existing tests/scanner; actual lab verifier results in handover |
| Database lifecycle | Refuses operational inventory; no reset | Preserved seed/runtime guards and release-state checks | KEEP | Existing guard regressions; historical destructive test is not repeated |
| Clean tree/embedded SHA | Stage tracked-dirt check; direct build could say UNKNOWN | All untracked dirt rejected; build checks HEAD and embeds it | FIX | Staging-control regression; final run from committed tree |
| Upgrade failure propagation | Process substitution could mask Python failure | Checked command substitution after shared platform/bundle checks | FIX | Bundle fixture and upgrade caller regression; upgrade not executed |
| Published inventory | Developer paths/internal source identity | Generic tracked/runtime inventory | FIX | Scanner and tracked text review |
| Missing helpers/modes | No dedicated clone completeness gate | LF, Git modes and required tracked files checked | FIX | `test_required_files_are_tracked`, `test_tracked_shell_lf_and_modes` |

The old executable OS blocks were replaced, not dropped. The replacements and
callers above are authored in this task. No scanner rules, signature checks,
TLS checks, SELinux/firewall enforcement, or database protections were relaxed.

## Fresh production code path

1. Root on supported RHEL with Bash/Git/Python-DNF/RPM/coreutils/sudo and normal
   host networking/trust; protected runtime config outside Git. Missing,
   unknown, duplicate and invalid inputs fail clearly before staging.
2. CONNECTED requires no explicit bundle path. Staging checks clean Git,
   records HEAD, inspects RHSM release, and requires accessible authorized
   RHEL repos. Satellite/RHUI equivalents are supplied as repo IDs; credentials,
   URLs, proxy, DNS, routing and trust remain normal administrator host settings.
3. Stage tools from RHEL only. Resolve the pinned application and target OS
   dependencies in empty installroots. Missing versions/modules or mismatched
   redhat-release content fail; sources and application versions never drift
   silently. No artificial minor version is supplied to satisfy the solver.
4. Verify keys/signatures/provenance/checksums; retain modules; install from
   file-only content in empty server/proxy roots. Generate an exact per-build
   lock and current-source metadata. Completion of these gates proves closure.
5. Bootstrap verifies bundle checksums/target and installs Ansible locally.
   Existing roles generate directories/schema/config/services/host encryption
   key. No lab cache, release tree, manifest or machine key is copied.
6. Lifecycle/database guards can refuse existing operational state. TLS needs
   the operator's valid certificate/key and a permitted SELinux web port.
   The verifier checks versions, services, frontend/Admin policy and security.

## External state and remaining risks

The lab has `/etc/zabbix-offline/bundle-root`, `release.json`,
`clean-seed-verified` and `backup.env`. Inspect them; never delete them to get
past guards. CONNECTED no longer consumes the pointer; verification intentionally
checks the installed artifact. AIRGAPPED still requires explicit matching
content and integrity. Matching minor is necessary, not a universal promise of
compatibility across every repository snapshot or pre-patched host.

The historical 313-RPM bundle retains its original build SHA. It must not be
relabeled as generated from this task. A new package count/embedded SHA requires
successful staging, currently blocked by lab source access. RHEL 9.7 repository
availability of the pinned applications/modules, fresh install, proxy/TLS and
corporate policy remain unverified. Installed packages newer than a generated
lock can fail verification; the project must not downgrade them to force PASS.

Use INSTALL-RHEL9.md for all required runtime keys and host prerequisites. The
final handover supplies actual branch/SHA, remote-clone results and copy/paste
commands. Shellcheck is run only if already installed. No new framework, OS
rebuild, database reset or repository reconfiguration is part of this task.

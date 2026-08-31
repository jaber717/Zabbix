# M1 Acceptance

M1 stopped at the mandated dependency-resolution failure condition. No
unapproved repository was introduced and no downstream result is inferred.

| Gate | Status | Evidence / reason |
|---|---|---|
| Compatibility profile implemented | PASS | `compat/zabbix-7.0.yaml`; parsed and validated on the Build VM. |
| RHEL 9.6 pinned | PASS | Build preflight and safety closeout returned release 9.6. |
| Zabbix 7.0.30 pinned | PASS | Compatibility profile and exact resolver input. |
| PostgreSQL 16 target represented | PASS | Compatibility profile and disposable module-enable transaction. |
| PHP 8.3 target represented | PASS | Compatibility profile and disposable module-enable transaction. |
| nginx 1.24 target represented | PASS | Compatibility profile and disposable module-enable transaction. |
| Python ABI resolved or explicitly parameterised | PASS | CPython 3.11 decision documented; wheel pipeline remains parameterized. |
| Clean build context used | PASS | Empty RPM database under `/var/lib/zabbix-offline-build/`; build log. |
| Approved repositories only | PASS | Clean repolist contained BaseOS, AppStream, and `m1-zabbix`. |
| NetBox offline repositories have zero build influence | PASS | Source assertion passed; they are absent from clean repolist. |
| Complete dependency closure generated | FAIL | Exact Zabbix server requires `fping`; no provider exists in approved sources. |
| `--alldeps`-equivalent behavior validated | FAIL | The actual `--resolve --alldeps` transaction stopped on missing `fping`. |
| RPM lockfile generated | NOT-EXECUTED | Pipeline stops before lock generation on unresolved closure. |
| RPM provenance recorded | NOT-EXECUTED | No complete payload set existed. |
| All RPM payloads downloaded | FAIL | Dependency resolution failed before a complete download. |
| All RPM signatures verified | NOT-EXECUTED | No complete payload set existed. |
| Modular metadata preserved | NOT-EXECUTED | Filter/parser unit probe passed, but no final repository was built. |
| Local DNF repository generated | NOT-EXECUTED | Blocked by incomplete closure. |
| Local-only module queries work | NOT-EXECUTED | No final local repository existed. |
| Local-only package resolution works | NOT-EXECUTED | No final local repository existed. |
| Local-only disposable-root installation tested | NOT-EXECUTED | No final local repository existed. |
| Build host RPM/module state protected | PASS | Post-build hashes equal post-tooling pre-build hashes; root removed. |
| Wheel pipeline prepared | PASS | ABI-parameterized script and intentionally empty lock were syntax checked. |
| Ansible offline requirement addressed | PASS | RHEL `ansible-core` is an explicit root; no external collection is declared. |
| BUILD-INFO generated | NOT-EXECUTED | Assembly stage was not reached. |
| RPM-MANIFEST generated | NOT-EXECUTED | Assembly stage was not reached. |
| MANIFEST generated | NOT-EXECUTED | Assembly stage was not reached. |
| SHA256SUMS generated | NOT-EXECUTED | Assembly stage was not reached. |
| Artifact built from allow-list | NOT-EXECUTED | Assembly stage was not reached. |
| Artifact secret scan clean | NOT-EXECUTED | No artifact existed. |
| Artifact hygiene scan clean | NOT-EXECUTED | No artifact existed. |
| Lab leakage test clean | NOT-EXECUTED | No artifact existed. |
| Reproducibility test passed | NOT-EXECUTED | First build did not complete. |
| Negative tests executed/documented | NOT-EXECUTED | Stop condition precluded post-build negative suite. |
| OFFLINE-BUILD.md complete | PASS | Reproduction, isolation, trust, lock, failure, and cleanup are documented. |
| M1 evidence committed | PASS | Blocked-run evidence commit `499f35a`. |
| Git working tree clean | PASS | Verified after the final status commit. |

## Blocker

- EXPECTED: The approved BaseOS, AppStream, and official Zabbix repositories
  provide the complete runtime dependency closure.
- ACTUAL: `zabbix-server-pgsql-7.0.30-release1.el9.x86_64` requires the `fping`
  capability; the approved-source provider query produced no package rows.
- IMPACT: Closure, lockfile, payload verification, final module repository,
  local-only install, artifact, reproducibility, and negative tests cannot run.
- RECOMMENDATION: The owner/architect must approve a supported source for
  `fping` or a separately controlled, vendor-verified `fping` RPM supply-chain
  path. Do not enable EPEL or another repository implicitly.

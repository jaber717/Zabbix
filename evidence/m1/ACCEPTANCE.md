# M1 Acceptance

M1 is complete. The original dependency-gate stop is retained under
`evidence/m1/resolution/`; the owner-approved amendment then permitted only the
official Zabbix non-supported RHEL 9 x86_64 source and only for the pinned
`fping` RPM. No EPEL or other source was introduced.

Accepted runs:

- Build 1: `m1-accepted-build1`, result `PASS`.
- Build 2: `m1-accepted-build2`, result `PASS`.
- Reproducibility comparison: `PASS`, including byte-identical generated
  repository content.

| Gate | Status | Evidence / result |
|---|---|---|
| Compatibility profile implemented | PASS | `compat/zabbix-7.0.yaml`; parsed and enforced by both builds. |
| RHEL 9.6 x86_64 pinned | PASS | Build preflight and final host closeout. |
| Zabbix 7.0.30 pinned | PASS | Compatibility profile, target set, lockfile, and installed-package evidence. |
| PostgreSQL 16 represented | PASS | 7 selected modulemd documents; local-only enable/install passed. |
| PHP 8.3 represented | PASS | 2 selected modulemd documents; local-only enable/install passed. |
| nginx 1.24 represented | PASS | 4 selected modulemd documents; local-only enable/install passed. |
| Python ABI resolved or explicitly parameterized | PASS | CPython 3.11 selected; wheel requirements intentionally empty until M4. |
| Fresh clean build context used | PASS | Each accepted run used a new empty RPM database below `/var/lib/zabbix-offline-build/`. |
| Approved repositories only | PASS | Source repolist contained only BaseOS, AppStream, `m1-zabbix`, and `m1-zabbix-nonsupported`. |
| Non-supported source constrained | PASS | Exactly one locked package: `fping-0:5.1-1.el9.x86_64`; scope assertion and negative test passed. |
| NetBox offline repositories have zero build influence | PASS | They are absent from clean repolist and every locked provenance row. |
| Complete dependency closure generated | PASS | 313 RPMs resolved with `--resolve --alldeps` and weak dependencies disabled. |
| `--alldeps`-equivalent behavior validated | PASS | Both accepted builds executed the actual `dnf download --resolve --alldeps` transaction. |
| RPM lockfile generated | PASS | Committed `rpm-lockfile.txt`; both candidates are byte-identical to it. |
| RPM provenance recorded | PASS | BaseOS 167; AppStream 132; official Zabbix 13; non-supported `fping` 1. |
| All RPM payloads downloaded | PASS | 313 RPMs present in each accepted repository. |
| All RPM signatures verified | PASS | Isolated RPM database; all 313 files have trusted `OK` signature/digest evidence using Red Hat and pinned Zabbix keys. |
| `fping` trust verified | PASS | SHA256 `973ea94723ef69a9196c9f72f44ca414b7857a75ccc02e8a6492293fb010073c`; key fingerprint `D9AA 84C2 B617 479C 6E4F CF4D 19F2 4753 08EF A7DD`. |
| Modular metadata preserved | PASS | 13 selected documents; module metadata hash evidence retained. |
| Local DNF repository generated | PASS | `createrepo_c` repository with validated module metadata. |
| Local-only module queries work | PASS | PostgreSQL 16, PHP 8.3, and nginx 1.24 listed from `m1-local`. |
| Local-only package resolution works | PASS | External repositories disabled; target and proxy queries passed. |
| Local-only disposable-root installation tested | PASS | Main PostgreSQL/nginx target passed; pgsql and sqlite3 proxies passed in separate roots. |
| Build host RPM/module state protected | PASS | Pre/post RPM and module hashes match in both builds; no host Zabbix RPM exists. |
| Wheel pipeline prepared | PASS | CPython 3.11 parameterized; zero requirements and zero wheels intentionally recorded. |
| Ansible offline requirement addressed | PASS | `ansible-core` is locked from AppStream; no external collection is declared. |
| BUILD-INFO generated | PASS | Retained under `evidence/m1/artifact/`. |
| RPM-MANIFEST generated | PASS | Exact NEVRA/source/SHA256 manifest retained. |
| MANIFEST generated | PASS | Release allow-list manifest retained. |
| SHA256SUMS generated | PASS | Release-tree checksum inventory retained. |
| Artifact built from allow-list | PASS | Both artifact-verification runs returned `PASS`. |
| Artifact secret scan clean | PASS | Automated release-tree secret-pattern scan returned `PASS`. |
| Artifact hygiene scan clean | PASS | Top-level allow-list, forbidden-file, manifest-coverage, and checksum checks returned `PASS`. |
| Lab leakage test clean | PASS | Negative suite returned `LAB_LEAKAGE=PASS`. |
| Reproducibility test passed | PASS | Lock, module metadata, allow-list, provenance, and repository bytes all match. |
| Negative tests executed/documented | PASS | All nine mandatory negative cases returned `PASS`. |
| OFFLINE-BUILD.md complete | PASS | Reproduction, isolation, trust, lock, failure, cleanup, and accepted result documented. |
| M1 evidence committed | PASS | This record and the accepted raw evidence are included in the M1 closeout commit. |
| Git working tree clean | PASS | Staged checks passed; post-commit status is part of the final handover. |

## Accepted artifact

- Filename: `zabbix-rhel96-offline-1.0.0-build1.tar.gz`
- Accepted copy: Build 2 output
- Size: `178093296` bytes
- SHA256: `dbcd9a1185a21f1bc44bff356f06088ac63d77a5bb8fe539ad573280d9cef42b`
- Local staging: `dist/m1-accepted-build2/`

The artifact filename is the pinned release name for both reproducibility runs;
the run identity is carried in the external build evidence. Artifact hashes may
differ because `BUILD-INFO.json` records each permitted build timestamp. The
comparison instead proves identical lockfile, module metadata, file allow-list,
RPM checksums/provenance, and byte-identical repository content.

## M2 gate

M1 has no remaining blocker. M2 is ready for a separate explicit authorization;
it was not started by this milestone.

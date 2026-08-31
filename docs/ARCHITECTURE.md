# Architecture

## M1 build boundary

The connected RHEL 9.6 Build VM is a supply-chain staging system, not a Zabbix
runtime target. A clean installroot resolves the explicit Phase-1 roots and full
dependency closure from only Red Hat BaseOS, Red Hat AppStream, and official
Zabbix 7.0 content, plus the narrowly approved official Zabbix non-supported
source for `fping` only. The output is a curated, module-aware local DNF
repository inside a pre-install release candidate.

The release includes Zabbix server/frontend/Agent 2/tooling/web-service packages,
PostgreSQL and SQLite proxy packages for later use, PostgreSQL 16, PHP 8.3,
nginx 1.24, RHEL `ansible-core`, target safety utilities, and CPython 3.11. It
does not include the MySQL proxy, external Ansible collections, speculative
Python dependencies, credentials, lab fixtures, or M2 installer logic.

Build correctness is proven in a second empty installroot using only the local
file repository. Host-installed RPMs and host module state are outside the
dependency model and are hashed before and after each pipeline run.

## Trust model

Vendor package signatures are the RPM trust boundary. Red Hat and Zabbix public
keys are included; the Zabbix fingerprint is pinned. File and package hashes,
source repository IDs, and manifests detect transfer or lock drift. Repository
metadata is not GPG-signed in M1 because no independently custodied repository
signing key exists; this is stated as `repo_gpgcheck=0`, never hidden or faked.
The non-supported provenance of `fping` remains explicit and does not extend to
any other package.

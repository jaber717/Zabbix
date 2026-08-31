# SPEC-01 — Offline Build

## Build boundary

Build on an Internet-connected RHEL 9.6 x86_64 system, but resolve from a clean,
isolated context such as `dnf --installroot=<clean-buildroot>`. Correctness must
not depend on packages already installed on the build host or operator memory.
Use complete dependency closure, including `--resolve` and `--alldeps` where
appropriate. Milestone 0 does not execute a build.

## Compatibility and locks

- Maintain version data in `compat/zabbix-7.0.yaml`; add other major profiles
  only after approval.
- Record exact Zabbix, RHEL, PostgreSQL, PHP, nginx, Python minor/ABI, package
  names, schema paths, and version-specific behavior.
- Do not select Python until target RHEL discovery confirms an approved minor.
- Pin resolved versions and retain repository/source provenance.

## RPM and module requirements

- Resolve a complete RPM dependency closure for a clean disconnected target.
- Preserve valid RHEL modular metadata for PostgreSQL, PHP, nginx, and any other
  module-managed content. Do not preselect a metadata-generation mechanism before
  testing the available supported tooling.
- With all external repositories disabled, the offline repository must support
  required `dnf module list` and `dnf module enable` operations.
- Verify vendor RPM signatures and fail closed on GPG verification failure.

## Python bundle

Build wheels for the approved RHEL Python ABI in an isolated context. Include all
transitive dependencies, hashes, licenses/provenance where available, and an
offline installation test. No runtime PyPI access is allowed.

## Artifact assembly

The release must contain the curated installer inputs, offline RPM repository,
wheelhouse, configuration templates, documentation, and compatibility profile.
It must produce an artifact tarball, `SHA256SUMS`, an individual SHA256 checksum,
`MANIFEST.txt`, `RPM-MANIFEST.txt`, `BUILD-INFO.json`, and `CHANGELOG`; add an
SBOM only where it will be consumed. The source repository and corporate artifact
are distinct products.

## Verification gates

- Rebuild from declared inputs and a clean build root.
- Test repository metadata and dependency closure with external repos disabled.
- Verify all hashes and vendor signatures.
- Scan the staged artifact for secrets, unapproved files, placeholders, and lab
  values before packaging and again after extraction.
- Record tool versions, input repositories, timestamps, profile, and hashes in
  build information without credentials.

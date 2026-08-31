# SPEC-01 — Offline Build

## Build boundary

Build on an Internet-connected RHEL 9.6 x86_64 system, but resolve from a clean,
isolated context such as `dnf --installroot=<clean-buildroot>`. Correctness must
not depend on packages already installed on the build host or operator memory.
Use complete dependency closure, including `--resolve` and `--alldeps` where
appropriate. M0/M0.5 did not execute a build.

## Approved source decision — M0.5

Verified source identifiers for RHEL 9.6 x86_64 are:

- `rhel-9-for-x86_64-baseos-rpms`
- `rhel-9-for-x86_64-appstream-rpms`
- official Zabbix 7.0 RHEL 9 x86_64 source at
  `https://repo.zabbix.com/zabbix/7.0/rhel/9/x86_64/`
- narrowly approved official Zabbix non-supported RHEL 9 x86_64 source at
  `https://repo.zabbix.com/non-supported/rhel/9/x86_64/`, restricted to the
  `fping` package only

M1 must use `--disablerepo='*'` and explicitly enable only approved source IDs in
the clean build context. `netbox-offline-base` and `netbox-offline-modules` are
unrelated prior artifacts and must have zero influence. M0.5 observed official
key fingerprint `4C3D 6F2C C75F 5146 754F C374 D913 219A B533 3005`; M1 must
still download RPM payloads and verify their vendor signatures before inclusion.

The non-supported source is a documented exception for the Zabbix Server
`fping` runtime requirement. M1 pins `fping-0:5.1-1.el9.x86_64`, restricts that
repository with `includepkgs=fping`, and fails if any other package is attributed
to it. This exception does not authorize EPEL, compilation, or another package
from the non-supported area. The package's upstream support classification must
remain visible in provenance and operator documentation.

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

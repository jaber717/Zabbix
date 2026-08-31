# Offline Build Pipeline

This procedure builds the M1 pre-install release candidate on the verified RHEL
9.6 x86_64 Build VM. It does not install or configure a production Zabbix
system. `compat/zabbix-7.0.yaml` is the single version and source authority.

## Prerequisites

- RHEL 9.6 x86_64 with the subscription release pinned to 9.6 and SELinux
  Enforcing.
- Usable `rhel-9-for-x86_64-baseos-rpms` and
  `rhel-9-for-x86_64-appstream-rpms` sources.
- HTTPS access to the official Zabbix 7.0 RHEL 9 x86_64 repository.
- Passwordless approved `sudo` for disposable installroots and RPM database
  operations.
- `dnf-plugins-core`, `createrepo_c`, `modulemd-tools`,
  `python3-dnf-plugin-modulesync`, `jq`, GnuPG, RPM tools, and tar. M1 installed
  only the last three missing build-tool packages and their direct libraries,
  using BaseOS/AppStream with every other repository disabled.

The Build VM may already contain runtime packages. The pipeline deliberately
ignores them: every resolve and install test uses a newly initialized RPM
database beneath `/var/lib/zabbix-offline-build/`.

## Build

From the repository root on the Build VM:

```bash
chmod +x build/*.sh build/lib/*.py
export BUILD_GIT_COMMIT="$(git rev-parse HEAD)"
export BUILD_GIT_DIRTY=false
export SOURCE_DATE_EPOCH="$(git show -s --format=%ct HEAD)"
RUN_ID=m1-run1 OUTPUT_DIR="$PWD/build/out/m1-run1" UPDATE_LOCK=1 build/build.sh
```

`UPDATE_LOCK=1` is permitted only for an intentional release refresh. Review the
candidate diff and provenance before committing `rpm-lockfile.txt`. Routine and
reproducibility builds omit it and fail if resolution drifts:

```bash
RUN_ID=m1-run2 OUTPUT_DIR="$PWD/build/out/m1-run2" build/build.sh
build/compare-builds.sh build/out/m1-run1 build/out/m1-run2 \
  evidence/m1/reproducibility/comparison.txt
build/run-negative-tests.sh build/out/m1-run2 \
  evidence/m1/negative-tests/results.txt
```

## Isolation and module handling

Source commands always use `--installroot`, `--releasever=9.6`,
`--disablerepo='*'`, and only the approved BaseOS, AppStream, and temporary
official Zabbix source. An automated assertion rejects NetBox, EPEL, Remi, PGDG,
Rocky, Alma, or CentOS source visibility.

M0.5 proved that `/var/tmp` is unsuitable for the clean RPM database under the
VM's SELinux policy. M1 therefore uses a unique directory immediately beneath
`/var/lib/zabbix-offline-build/`. Cleanup validates that exact prefix before
recursive removal and is registered as an exit/signal trap.

PostgreSQL 16, PHP 8.3, and nginx 1.24 are enabled only inside the disposable
source and local-test installroots. The build filters the original AppStream
modulemd documents for those streams, parses them with `modulemd-merge`, and adds
the validated metadata to the generated repository. A second empty installroot
then lists, enables, resolves, and installs from that local file repository with
all external repositories disabled.

The Red Hat `modulesync --resolve` path was tested in a disposable probe and
rejected for this runtime artifact: a single nginx stream expanded to 707
packages including build/source and i686 content. The probe was interrupted and
cleaned. M1 retains supported upstream modulemd while the actual x86_64/noarch
runtime transaction is resolved with `dnf download --resolve --alldeps`.

## Supply-chain and repository policy

Every RPM is verified in a temporary RPM database containing only the Build
VM's official Red Hat release keys and the Zabbix public key whose fingerprint
must equal `4C3D 6F2C C75F 5146 754F C374 D913 219A B533 3005`. Any failed or
unknown signature stops the build. Exact NEVRA, source repository ID, and SHA256
are recorded in the committed lockfile and release RPM manifest.

The target `.repo` file uses `gpgcheck=1`. `repo_gpgcheck=0` is explicit because
M1 has no approved, independently controlled repository-metadata signing key.
Vendor RPM signatures and release checksums remain mandatory; no private key is
created or bundled.

## Outputs and verification

Each output directory contains the repository, evidence, controlled release
tree, and `dist/`. The expected artifact is
`zabbix-rhel96-offline-1.0.0-build1.tar.gz` with its individual sidecar plus
`SHA256SUMS`, `MANIFEST.txt`, `RPM-MANIFEST.txt`, and `BUILD-INFO.json`.

`build/verify-build.sh` enforces the release-tree allow-list, bidirectional
manifest coverage, file hashes, RPM lock equality, modular metadata presence,
forbidden file/secret patterns, and lab-identifier exclusion from runtime paths.
Verify after transfer with the sidecar first, then extract and run
`sha256sum -c SHA256SUMS` inside the extracted tree.

The wheel builder is ready for CPython 3.11 but M1 requirements are intentionally
empty. M4 must define real dependencies and exact hashes; future installation
must use `--no-index`, `--find-links`, and `--require-hashes`.

## Failure and cleanup

Stop rather than broaden sources if a package, signature, module stream, or
local-only resolution fails. Do not change the release pin, host module streams,
SELinux, or repository configuration. Failed runs remove only their validated
`/var/lib/zabbix-offline-build/m1-*` root. Generated `build/out/` directories are
not deleted automatically and may be removed manually only after their absolute
path and evidence retention needs are checked.

The first M1 execution stopped as designed: the official
`zabbix-server-pgsql-7.0.30-release1.el9.x86_64` package requires `fping`, and no
provider was visible from the approved sources. Do not resume the build until a
supported source or controlled RPM ingestion decision is explicitly approved.

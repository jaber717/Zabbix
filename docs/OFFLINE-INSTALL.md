# Offline staging and installation

## Build the transport bundle

Run only on an authorized RHEL 9.x x86_64 staging host with matching target
minor/content, configured BaseOS/AppStream access, and the
tools checked by `build/build.sh` available:

```bash
git clone --branch staging https://github.com/jaber717/Zabbix.git
cd Zabbix
sudo -n true
sudo RUN_ID=release-build1 OUTPUT_DIR=/var/tmp/zabbix-release-build1 \
  scripts/stage-offline-bundle.sh
```

The pipeline uses empty RPM/install roots, inherits the host's effective DNF
release (or its real explicit administrator pin), selects PostgreSQL
16, PHP 8.3, and nginx 1.24, resolves with `--resolve --alldeps`, generates an
exact per-build lock from authorized target repositories, verifies keys and RPM signatures,
preserves module metadata, and performs local-only installations. Run a second
fresh build and `build/compare-builds.sh` for reproducibility qualification.
The historical `manifests/rpm-lockfile.txt` remains immutable audit evidence;
direct `build/build.sh` defaults to frozen comparison. CONNECTED staging uses
`LOCK_MODE=resolve` without modifying Git. Bundle lock, RPM manifest, NEVRAs,
checksums and source policy remain exact within each generated artifact.
Matching bundle/target minor is necessary, not a claim that every possible
repository snapshot or already-patched target is compatible. Rebuild and test
on the intended content; never downgrade target OS packages to fit an old bundle.

Stop if a dependency is absent. Do not enable EPEL or broaden sources. The
non-supported Zabbix repository is queried separately and must expose exactly
the pinned `fping` package to the build.

## Transfer

Copy the generated `.tar.gz` and adjacent `.sha256` by an approved offline
method. Do not upload the payload to GitHub. On the destination:

```bash
sha256sum -c zabbix-rhel9-offline-1.0.0-build1.tar.gz.sha256
sudo install -d -o root -g root -m 0755 /opt/zabbix-offline/release
sudo tar -xzf zabbix-rhel9-offline-1.0.0-build1.tar.gz \
  -C /opt/zabbix-offline/release
```

Set `INSTALL_MODE=airgapped` and
`OFFLINE_BUNDLE_ROOT=/opt/zabbix-offline/release` in the protected runtime file,
then run `sudo ./install.sh` and `sudo ./verify.sh`. Installation DNF commands
explicitly disable all external repositories.

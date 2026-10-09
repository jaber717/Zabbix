# Install, upgrade, rollback (offline package)

Needs on the target: bash, tar, sha256sum, Python 3.9+ (LAB VM: 3.12) and PyYAML `>=6.0,<7.0`. **Nothing is downloaded.** Production is isolated: this package is built elsewhere, carried over, verified by checksum, and installed with the same scripts. No script contacts Zabbix, and none of them enables anything. (The package does not bundle wheels; install PyYAML from your own wheelhouse: `python3 -m pip install --no-index --find-links <wheelhouse> 'PyYAML>=6.0,<7.0'`.)

## Build (on a workstation / CI)
```bash
release/build-package.sh dist/         # -> dist/netops-hardware-health-<ver>.tar.gz + .sha256
```
The build refuses if any file looks like it holds a credential, excludes `state/`, `evidence/`, caches, and embeds `MANIFEST.sha256` (every file) and `VERSION`. Operator-editable files ship as `config.defaults/`.

## Install
```bash
sudo release/install.sh netops-hardware-health-<ver>.tar.gz --prefix /opt/netops-hardware-health
```
Order of operations (any failure aborts before the switch): package checksum (mandatory `.sha256` beside it) -> Python/PyYAML -> unpack to staging -> manifest verified -> release placed in `releases/<ver>` -> `config/` created from defaults **only if absent** (an existing config is never overwritten; new default files are added) -> `state/` (0700) shared -> offline self-test of the new release (`vendors check`, `simulate`, `messages`) -> atomic `current` switch, previous recorded. Re-running is idempotent.

```
<prefix>/releases/<ver>/   immutable code      <prefix>/current  -> release in use
<prefix>/previous          -> release replaced  <prefix>/config/  operator config   <prefix>/state/  backups, ownership, ledgers
```

## Verify the deployment (offline)
```bash
<prefix>/current/release/verify-deployment.sh <prefix>
```
Manifest of the running release, config/state present, `state` is 0700, Python/PyYAML, the three offline self-tests, CLI version equals `VERSION`, **no config requests the action enabled**, no credential-like value in config. A modified file fails with `manifest`.

## Upgrade
```bash
sudo release/upgrade.sh netops-hardware-health-<newver>.tar.gz --prefix <prefix>
```
Writes `<prefix>/backups/pre-upgrade-<stamp>.tar.gz` (config + state, 0600) first, then installs as above. Config and state are preserved (tested).

## Rollback
```bash
sudo release/rollback.sh --prefix <prefix>        # code only: atomic switch back to `previous`, manifest-checked
tar -xzf <prefix>/backups/pre-upgrade-<stamp>.tar.gz -C <prefix>   # only if the upgrade changed config/state
```
Zabbix-side objects have their own rollbacks (`action rollback`, `template rollback`, tag RESTORE plan) - see `TELEGRAM-RUNBOOK.md`.

## LAB validation (read-only)
```bash
ZABBIX_HARDWARE_URL_LAB=... ZABBIX_HARDWARE_TOKEN_LAB=... <prefix>/current/release/validate-lab.sh <prefix>
```
Runs the offline gates, `labsim`, `synthetic audit-probe`, `action plan`, `template plan`. Exit 0 only if everything passed; prints "no live Telegram delivery was tested".

## Production
Not installed or accessed by this release. Install the identical package offline; the CLI refuses `action` / `template` management for `--env production`, and the production inventory stays `hosts: {}` until real sensors are verified.

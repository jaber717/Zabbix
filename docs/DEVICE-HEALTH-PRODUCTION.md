# Device Health & Capacity production installation

Install only from the immutable `device-health-v1.0.0` tag. Review the runtime capability/profile and storage-rollup policy before enabling the module in production. The installer preserves an existing runtime policy and first-observed grace state.

```bash
git clone --depth 1 --branch device-health-v1.0.0 https://github.com/jaber717/Zabbix.git
cd zabbix-platform
sha256sum --quiet -c scripts/device-health-release.sha256
sudo bash scripts/install-device-health.sh --preflight
sudo bash scripts/install-device-health.sh
sudo bash scripts/verify-device-health.sh
```

Then scan and enable **Device Health & Capacity** under Zabbix Administration → General → Modules and add the widget to the desired dashboard.

Rollback preserves `/var/lib/zabbix/device-health`:

```bash
sudo bash scripts/rollback-device-health.sh --confirm-module-disabled --restore-latest
```

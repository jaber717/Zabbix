# Zabbix 7.0 on RHEL 9.x

Reproducible deployment source for Zabbix 7.0.30, PostgreSQL 16, nginx,
PHP-FPM, and Agent 2 on RHEL 9.x x86_64. It supports connected staging and
airgapped installation while keeping every RPM and every runtime secret out of
Git.

Branch: **staging**. Historical RHEL 9.6 qualification is recorded separately
from the current portability changes. RHEL 9.7 production has not been tested
end to end. See [production readiness](docs/PRODUCTION-READINESS.md) for the
current blockers, test boundaries, and production prerequisites.

## Quick start

```bash
git clone --branch staging https://github.com/jaber717/Zabbix.git
cd Zabbix
sudo install -o root -g root -m 0600 .env.example /root/zabbix-install.env
sudoedit /root/zabbix-install.env
sudo ./install.sh
sudo ./verify.sh
```

Use the operator-supplied deployment password in the protected file; never add
its value to this repository. See [installation](docs/INSTALL-RHEL9.md),
[offline staging](docs/OFFLINE-INSTALL.md), and
[Huawei onboarding](docs/HUAWEI-ONBOARDING.md).

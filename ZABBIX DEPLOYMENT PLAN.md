# ZABBIX DEPLOYMENT PLAN

Use this plan for the first production deployment on a fresh VM.

Current requested target: RHEL 9.7 x86_64 CONNECTED. General OS acceptance is
RHEL 9.x x86_64. RHEL 9.7 has NOT been tested end to end. Read
`docs/PRODUCTION-READINESS.md` and the final handover before deployment;
CONNECTED lab staging remains blocked by missing authorized RHEL repositories.

> Replace only values inside `< >`.
> The deployment account does **not** require direct root login or unrestricted sudo.
> The commands below are the required administrative commands for the deployment.

## 0. System Team Requirements

### VM

```text
OS: RHEL 9.x x86_64 (production target 9.7)
CPU: 6 vCPU
RAM: 16 GB
Disk: 100 GB total
SELinux: Enforcing
```

### Partitioning

```text
/boot              2 GB
swap                6 GB
/var/lib/pgsql     55 GB
/                  remaining space (~37 GB)
```

- XFS and LVM are preferred.
- No separate `/opt` partition is required. `/opt` remains under `/`.
- The 100 GB is the **total VM disk**, not an additional Zabbix data disk.
- PostgreSQL/Zabbix database data is stored under `/var/lib/pgsql`.

### Deployment Account

```text
Username: <USE YOUR CORPORATE / DEPLOYMENT USERNAME HERE>
SSH access: Required
Direct root SSH: Not required
Full unrestricted sudo: Not required
```

The system team should permit this account to run the following deployment commands with sudo:

```text
/usr/bin/git clone --branch staging https://github.com/jaber717/Zabbix.git /opt/Zabbix
/usr/bin/install -d -o root -g root -m 0755 /opt/zabbix-offline/release-tree
/usr/bin/tar -xzf /tmp/zabbix-offline-bundle.tar.gz -C /opt/zabbix-offline/release-tree
/usr/bin/install -d -o root -g root -m 0750 /etc/zabbix-deployment
/usr/bin/install -o root -g root -m 0600 /opt/Zabbix/.env.example /etc/zabbix-deployment/zabbix-install.env
sudoedit /etc/zabbix-deployment/zabbix-install.env
/opt/Zabbix/install.sh --config /etc/zabbix-deployment/zabbix-install.env
/opt/Zabbix/verify.sh --config /etc/zabbix-deployment/zabbix-install.env
/usr/sbin/ausearch -m AVC,USER_AVC -ts boot
/usr/bin/systemctl restart zabbix-server.service
/usr/bin/systemctl restart zabbix-agent2.service
/usr/bin/systemctl restart nginx.service
/usr/bin/systemctl restart php-fpm.service
/usr/bin/systemctl restart postgresql.service
/usr/bin/systemctl status zabbix-server.service
/usr/bin/systemctl status zabbix-agent2.service
/usr/bin/systemctl status nginx.service
/usr/bin/systemctl status php-fpm.service
/usr/bin/systemctl status postgresql.service
/usr/bin/systemctl reboot
```

`/opt/Zabbix` must remain root-owned and must not be writable by the deployment account.

---

## 1. Validate the VM

```bash
cat /etc/redhat-release
uname -m
getenforce
hostnamectl
ip addr
ip route
timedatectl
df -h
free -h
nproc
```

Required before continuing:

```text
ID=rhel; VERSION_ID matches ^9\.[0-9]+$
x86_64
SELinux: Enforcing
```

Take a VM snapshot:

```text
ZABBIX-PRE-INSTALL-CLEAN
```

---

## 2. Clone the Qualified Release

```bash
sudo /usr/bin/git clone --branch staging https://github.com/jaber717/Zabbix.git /opt/Zabbix
cd /opt/Zabbix
git rev-parse HEAD
```

Compare HEAD with the exact commit in the final hardening handover. That
handover distinguishes safe existing-host validation from the blocked
CONNECTED staging path. Do not treat an earlier release SHA as this candidate.

---

## 3. CONNECTED repository prerequisites

The system team must provide authorized BaseOS/AppStream repositories plus
normal DNS/proxy/CA access to the approved Zabbix upstreams. No files are copied
from the lab. CONNECTED installation stages a target-specific local bundle from
the current clean source. Inspect `/etc/zabbix-offline/` first; do not delete
state to bypass safeguards. See `docs/OFFLINE-INSTALL.md` only when deliberately
deploying AIRGAPPED with content compatible with that target minor.

---

## 4. Create the Production Configuration

Create the protected configuration directory and file:

```bash
sudo /usr/bin/install -d -o root -g root -m 0750 /etc/zabbix-deployment

sudo /usr/bin/install -o root -g root -m 0600 \
  /opt/Zabbix/.env.example \
  /etc/zabbix-deployment/zabbix-install.env
```

Edit it:

```bash
sudoedit /etc/zabbix-deployment/zabbix-install.env
```

Replace the file contents with the following and change only values inside `< >`:

```ini
INSTALL_MODE=connected
OFFLINE_BUNDLE_ROOT=

ZABBIX_SERVER_HOSTNAME=<USE YOUR ZABBIX SERVER HOSTNAME HERE>
ZABBIX_WEB_SERVER_NAME=<USE YOUR ZABBIX SERVER IP OR FQDN HERE>

ZABBIX_TIMEZONE=Asia/Riyadh
ZABBIX_FRONTEND_PORT=80

ZABBIX_DB_PASSWORD=<USE YOUR PASSWORD HERE>
ZABBIX_ADMIN_PASSWORD=<USE THE SAME PASSWORD HERE>

TLS_ENABLED=false
TLS_CERTIFICATE_FILE=
TLS_PRIVATE_KEY_FILE=

FIREWALL_WEB_SOURCES=<USE YOUR MANAGEMENT SUBNET HERE, DOCUMENTATION EXAMPLE 192.0.2.0/24>
FIREWALL_SERVER_SOURCES=<USE YOUR MANAGEMENT SUBNET HERE, DOCUMENTATION EXAMPLE 192.0.2.0/24>
FIREWALL_AGENT_SOURCES=<USE YOUR MANAGEMENT SUBNET HERE, DOCUMENTATION EXAMPLE 192.0.2.0/24>

BASEOS_REPO=
APPSTREAM_REPO=
```

### Password Rule

Use the **same password** for:

```text
ZABBIX_DB_PASSWORD
ZABBIX_ADMIN_PASSWORD
```

Password length:

```text
12-128 characters
```

Use only:

```text
A-Z
a-z
0-9
_ ! @ % ^ + = . , : $ -
```

Do **not** use spaces or characters such as:

```text
& # ( ) / ' "
```

---

## 5. Verify the Configuration File

```bash
sudo ls -l /etc/zabbix-deployment/zabbix-install.env
```

Expected owner and permissions:

```text
root root
-rw-------
```

---

## 6. Install Zabbix

```bash
sudo /opt/Zabbix/install.sh \
  --config /etc/zabbix-deployment/zabbix-install.env
```

Expected result:

```text
PASS: installation completed
```

If installation returns **FAIL**: **STOP**. Do not manually modify the deployment. Capture the error first.

---

## 7. Run Verification

```bash
sudo /opt/Zabbix/verify.sh \
  --config /etc/zabbix-deployment/zabbix-install.env
```

Expected result:

```text
ZABBIX DEPLOYMENT VERIFICATION: PASS
```

---

## 8. Check SELinux AVCs Manually

```bash
sudo /usr/sbin/ausearch -m AVC,USER_AVC -ts boot
```

Expected:

```text
<no matches>
```

If AVCs related to Zabbix, nginx, PHP-FPM, or PostgreSQL appear: **STOP and investigate**.

---

## 9. Test the Web Interface

Open:

```text
http://<USE YOUR ZABBIX SERVER IP OR FQDN HERE>
```

Login:

```text
Username: Admin
Password: <USE THE PASSWORD FROM ZABBIX_ADMIN_PASSWORD>
```

Confirm the frontend opens and the Zabbix server is running.

---

## 10. Take a Verified Snapshot

Snapshot name:

```text
ZABBIX-CLEAN-INSTALLED-VERIFIED
```

---

## 11. Reboot Test

Before reboot:

```bash
cat /proc/sys/kernel/random/boot_id
```

Reboot:

```bash
sudo /usr/bin/systemctl reboot
```

After the VM returns:

```bash
cat /proc/sys/kernel/random/boot_id

sudo /opt/Zabbix/verify.sh \
  --config /etc/zabbix-deployment/zabbix-install.env

sudo /usr/sbin/ausearch -m AVC,USER_AVC -ts boot
```

Required result:

```text
New boot ID
ZABBIX DEPLOYMENT VERIFICATION: PASS
No relevant SELinux AVCs
```

---

## 12. Huawei Pilot - One Device Only

Add one Huawei switch first.

```text
Host name:
<USE YOUR HUAWEI DEVICE HOSTNAME HERE>

SNMP IP:
<USE YOUR HUAWEI MANAGEMENT IP HERE>

Template:
Huawei VRP by SNMP

SNMP Version:
SNMPv3

Security Level:
authPriv

Username:
<USE YOUR SNMPv3 USERNAME HERE>

Authentication:
SHA-256

Authentication Password:
<USE YOUR SNMPv3 AUTH PASSWORD HERE>

Privacy:
AES-128

Privacy Password:
<USE YOUR SNMPv3 PRIVACY PASSWORD HERE>
```

Validate:

```text
SNMP = Available
CPU = Data
Memory = Data
Uptime = Data
Interfaces = Discovered
Traffic = Data
Errors / Discards = Data
```

---

## 13. FortiGate Pilot - One Device Only

Add one FortiGate after Huawei is working.

```text
Host name:
<USE YOUR FORTIGATE HOSTNAME HERE>

SNMP IP:
<USE YOUR FORTIGATE MANAGEMENT IP HERE>

Template:
FortiGate by SNMP

SNMP Username:
<USE YOUR SNMP USERNAME HERE>

Authentication Password:
<USE YOUR SNMP AUTH PASSWORD HERE>

Privacy Password:
<USE YOUR SNMP PRIVACY PASSWORD HERE>
```

Validate:

```text
SNMP = Available
CPU = Data
Memory = Data
Interfaces = Data
Sessions = Data
HA = Data (if applicable)
SD-WAN = Data (if configured)
```

---

## 14. GO / NO-GO

Proceed with bulk onboarding only when all of the following are PASS:

```text
Fresh Installation = PASS
verify.sh = PASS
SELinux AVC Check = PASS
Reboot = PASS
Post-Reboot verify.sh = PASS
Huawei Live Polling = PASS
FortiGate Live Polling = PASS
```

Do not enable NetBox synchronization, Grafana, bulk onboarding, or production TLS during this first deployment.

## Important Day-1 Rule

Treat this as a first-install deployment. Complete installation, verification, reboot, and initial validation before adding production hosts. Do not re-run `install.sh` after normal production hosts/users have been added unless the release procedure explicitly supports that state.

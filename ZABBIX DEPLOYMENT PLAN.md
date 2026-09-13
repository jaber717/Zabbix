# ZABBIX DEPLOYMENT PLAN

Use this plan for the first production deployment on a fresh VM.

> Replace only values inside `< >`.
> Do not change anything else unless required by your environment.

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
Red Hat Enterprise Linux release 9.6 (Plow)
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
sudo git clone --branch main https://github.com/jaber717/Zabbix.git /opt/Zabbix
cd /opt/Zabbix
git rev-parse HEAD
```

Expected qualified commit:

```text
d95b8cff931c030d3fd1257d095dfd6486e0d3e0
```

If the commit is different: **STOP**.

---

## 3. Copy the Offline Bundle to the VM

Copy the accepted bundle to:

```text
/tmp/zabbix-offline-bundle.tar.gz
```

Verify it:

```bash
sha256sum /tmp/zabbix-offline-bundle.tar.gz
```

Expected SHA-256:

```text
dbcd9a1185a21f1bc44bff356f06088ac63d77a5bb8fe539ad573280d9cef42b
```

If the checksum is different: **STOP**.

Extract it:

```bash
sudo install -d -m 0755 /opt/zabbix-offline/release-tree
sudo tar -xzf /tmp/zabbix-offline-bundle.tar.gz \
  -C /opt/zabbix-offline/release-tree
```

---

## 4. Create the Production Configuration

Copy the template:

```bash
sudo install -o root -g root -m 0600 \
  /opt/Zabbix/.env.example \
  /root/zabbix-install.env
```

Edit it:

```bash
sudoedit /root/zabbix-install.env
```

Replace the file contents with the following and change only values inside `< >`:

```ini
INSTALL_MODE=airgapped
OFFLINE_BUNDLE_ROOT=/opt/zabbix-offline/release-tree

ZABBIX_SERVER_HOSTNAME=<USE YOUR ZABBIX SERVER HOSTNAME HERE>
ZABBIX_WEB_SERVER_NAME=<USE YOUR ZABBIX SERVER IP OR FQDN HERE>

ZABBIX_TIMEZONE=Asia/Riyadh
ZABBIX_FRONTEND_PORT=80

ZABBIX_DB_PASSWORD=<USE YOUR PASSWORD HERE>
ZABBIX_ADMIN_PASSWORD=<USE THE SAME PASSWORD HERE>

TLS_ENABLED=false
TLS_CERTIFICATE_FILE=
TLS_PRIVATE_KEY_FILE=

FIREWALL_WEB_SOURCES=<USE YOUR MANAGEMENT SUBNET HERE, EXAMPLE 10.10.10.0/24>
FIREWALL_SERVER_SOURCES=<USE YOUR MANAGEMENT SUBNET HERE, EXAMPLE 10.10.10.0/24>
FIREWALL_AGENT_SOURCES=<USE YOUR MANAGEMENT SUBNET HERE, EXAMPLE 10.10.10.0/24>
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

## 5. Verify Configuration Permissions

```bash
sudo chown root:root /root/zabbix-install.env
sudo chmod 600 /root/zabbix-install.env
sudo ls -l /root/zabbix-install.env
```

Expected permissions:

```text
-rw-------
```

---

## 6. Install Zabbix

```bash
sudo /opt/Zabbix/install.sh
```

Expected result:

```text
PASS: installation completed
```

If installation returns **FAIL**: **STOP**. Do not manually modify the deployment. Capture the error first.

---

## 7. Run Verification

```bash
sudo /opt/Zabbix/verify.sh
```

Expected result:

```text
ZABBIX DEPLOYMENT VERIFICATION: PASS
```

---

## 8. Check SELinux AVCs Manually

```bash
sudo ausearch -m AVC,USER_AVC -ts boot
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
sudo reboot
```

After the VM returns:

```bash
cat /proc/sys/kernel/random/boot_id
sudo /opt/Zabbix/verify.sh
sudo ausearch -m AVC,USER_AVC -ts boot
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

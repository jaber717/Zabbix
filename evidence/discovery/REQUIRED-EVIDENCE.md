# Required Evidence

Save returned text exactly under `evidence/discovery/raw/`, removing only secret
values. Never paste credentials or authorization headers. These items remain
required because Milestone 0 could not obtain them safely.

## RHEL build VM baseline

**Why needed:** Proves target release/architecture, entitlements, enabled repos,
disk, Python ABI candidates, and module streams used by M1 compatibility and
dependency closure. The candidate host did not answer on TCP 22.

**Preconditions:** Power on the intended Internet-connected RHEL 9.6 x86_64 build
VM and provide authorized read-only SSH access.

**Exact safe commands:**

```bash
set -o pipefail
cat /etc/redhat-release
uname -m
subscription-manager status
dnf repolist --enabled
df -hT
command -v python3 || true
python3 --version || true
ls -1 /usr/bin/python3* 2>/dev/null || true
dnf module list postgresql
dnf module list php
dnf module list nginx
```

**Expected output type:** Plain-text OS/repository/disk/interpreter/module facts.
Do not include subscription identity, credentials, or private entitlement data.

**Save as:** `evidence/discovery/raw/rhel-build-baseline.txt`

## NetBox integration endpoints and permissions

**Why needed:** The approved integration requires both devices and VMs plus
eligibility metadata. The available read-only portal credential returned 403
through the client for virtual machines, tags, and custom fields.

**Preconditions:** An explicitly approved read-only NetBox API credential with
view permission for devices, virtual machines, sites, locations, roles, platforms,
manufacturers, tags, and custom fields. Do not broaden the existing credential in
Milestone 0; permission changes are NetBox writes and need later authorization.

**Exact safe API calls:**

```bash
# Supply the token through a protected runtime environment; never echo it.
curl --fail --silent --show-error \
  -H "Authorization: Token ${NETBOX_READ_TOKEN}" \
  -H 'Accept: application/json' \
  'https://<netbox>/api/virtualization/virtual-machines/?limit=1'
curl --fail --silent --show-error \
  -H "Authorization: Token ${NETBOX_READ_TOKEN}" \
  -H 'Accept: application/json' \
  'https://<netbox>/api/extras/tags/?limit=1'
curl --fail --silent --show-error \
  -H "Authorization: Token ${NETBOX_READ_TOKEN}" \
  -H 'Accept: application/json' \
  'https://<netbox>/api/extras/custom-fields/?limit=1'
```

**Expected output type:** HTTP 200 JSON collection shapes and counts. Sanitize
object content to infrastructure metadata and never save request headers.

**Save as:** `evidence/discovery/raw/netbox-required-endpoints.txt`

## NetBox/portal version contradiction

**Why needed:** NetBox `manage.py version` reported 6.0.8 while the running portal
health route and local source hardcode 4.6.9. Compatibility work cannot treat both
as current.

**Exact safe commands:**

```bash
/opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py version
grep -n '^NETBOX_VERSION' /opt/netbox-topology/app/main.py
curl --fail --silent --show-error http://127.0.0.1:8081/api/health
```

**Expected output type:** Actual NetBox version, declared portal version, health
JSON. A later authorized milestone must decide whether the portal is compatible
with NetBox 6.0.8; do not change the portal during discovery.

**Save as:** `evidence/discovery/raw/netbox-portal-version-revalidation.txt`

## PNETLab and EVE access

**Why needed:** M8 discovery/topology tests require emulator versions, management
addresses, and safe access boundaries.

**Preconditions:** Explicit authorization to start or otherwise access QEMU 110
and 120. They were stopped during M0 and were deliberately left untouched.

**Procedure:** After authorization, start through the normal Proxmox operational
process, record the guest versions and management reachability using read-only
commands, then stop only if the approved test plan says to do so.

**Expected output type:** Version and infrastructure metadata only.

**Save as:** `evidence/discovery/raw/emulator-baseline.txt`

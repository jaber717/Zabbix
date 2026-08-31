# Required Evidence

Save returned text exactly under `evidence/discovery/raw/`, removing only secret
values. Never paste credentials or authorization headers. These items remain
required because Milestone 0 could not obtain them safely.

## RHEL source repository readiness

**Already verified:** VM reachability/authenticated shell, RHEL 9.6 x86_64,
storage, current module metadata, current Python view, subscription-manager read
output, and current repository state. See `raw/rhel-build-baseline.txt` and
`raw/rhel-build-repository-readiness.txt`.

**Why still needed:** M1 requires usable, approved BaseOS/AppStream and other
source repositories in a clean build context. Current DNF enables only the
pre-existing NetBox offline repositories. Standard BaseOS/AppStream definitions
are visible but disabled. This does not prove their permanent availability or
unavailability.

**Preconditions:** The system/subscription owner restores or verifies approved
source access outside this M0 run and authorizes a subsequent read-only readiness
check. Do not register, attach, enable, disable, refresh, or edit repositories as
part of discovery.

**Exact safe commands:**

```bash
sudo -n subscription-manager status
sudo -n subscription-manager repos --list-enabled
sudo -n subscription-manager release --show
dnf repolist
dnf repolist --all
```

**Expected output type:** Approved BaseOS/AppStream and required build source IDs
shown usable for the intended build context. Do not save subscription identity,
organization identifiers, credentials, or private entitlement data.

**Save as:** `evidence/discovery/raw/rhel-source-readiness-revalidation.txt`

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

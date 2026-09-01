# Required Evidence

Save returned text exactly under `evidence/discovery/raw/`, removing only secret
values. Never paste credentials or authorization headers. These items remain
required because Milestone 0 could not obtain them safely.

## Resolved — RHEL source repository readiness

**Already verified:** VM reachability/authenticated shell, RHEL 9.6 x86_64,
storage, current module metadata, current Python view, subscription-manager read
output, and current repository state. See `raw/rhel-build-baseline.txt` and
`raw/rhel-build-repository-readiness.txt`.

M0.5 enabled and verified the standard BaseOS/AppStream repositories, verified
the official Zabbix 7.0 source, and passed an isolated clean-installroot query and
recursive-resolution test. Evidence is under `evidence/m0.5/`. No further source
readiness evidence is required before M1 approval. Full payload closure, RPM
signature verification, and offline metadata generation remain M1 deliverables.

## NetBox integration endpoints and permissions — partially resolved, still blocked

**Why needed:** The approved integration requires both devices and VMs plus
eligibility metadata. The available read-only portal credential returned 403
through the client for virtual machines, tags, and custom fields. M4 reconfirmed
those 403s and additionally proved virtual-machine interfaces are denied.

**Preconditions:** An explicitly approved read-only NetBox API credential with
view permission for devices, virtual machines and VM interfaces, sites,
locations, roles, platforms, manufacturers, tags, and custom fields. The minimum
missing actions are `virtualization.view_virtualmachine`,
`virtualization.view_vminterface`, `extras.view_tag`, and
`extras.view_customfield`. Permission changes remain operator work; M4 did not
grant them.

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
  'https://<netbox>/api/virtualization/interfaces/?limit=1'
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

**Current evidence:** `evidence/m4/raw/netbox-api-preflight.txt`. After the
operator grants the four exact views, save the successful recheck as
`evidence/m4/raw/netbox-api-preflight-after-permission.txt`.

## Resolved — NetBox/portal version classification

M4 proved that the generic `manage.py version` output 6.0.8 is Django's version,
not NetBox's. Authenticated `/api/status/` reports NetBox 4.6.9, Django 6.0.8,
and the API header is 4.6. `/opt/netbox` resolves to `/opt/netbox-4.6.9`, and
portal health reports NetBox 4.6.9.

**Exact safe commands:**

```bash
/opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py version
grep -n '^NETBOX_VERSION' /opt/netbox-topology/app/main.py
curl --fail --silent --show-error http://127.0.0.1:8081/api/health
```

**Evidence:** `evidence/m4/raw/netbox-api-preflight.txt` and
`evidence/m4/raw/netbox-version-reconciliation.txt`. No further version evidence
is required for M4. Portal feature work remains M6 scope.

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

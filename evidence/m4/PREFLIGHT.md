# M4 NetBox Preflight

Captured 2026-09-01 against authoritative LXC 9000 (`netbox-demo`,
`192.168.1.89`) with the existing credential. Every NetBox API operation was
GET; no token or response record was saved.

## Version result

The version contradiction is resolved:

- `/api/status/` reports `netbox-version=4.6.9` and
  `netbox-full-version=4.6.9`.
- The response header advertises API version 4.6.
- `/opt/netbox` resolves to `/opt/netbox-4.6.9`.
- The value `6.0.8` from `manage.py version` is the installed Django version;
  `/api/status/` explicitly labels it `django-version=6.0.8`.
- The existing portal health response also reports NetBox 4.6.9.

Evidence: `raw/netbox-api-preflight.txt` and
`raw/netbox-version-reconciliation.txt`.

## Permission matrix

| Resource | Result | Live result |
|---|---|---|
| `/api/` | PASS | HTTP 200, API 4.6 |
| `/api/status/` | PASS | HTTP 200, NetBox 4.6.9 |
| `/api/dcim/devices/` | PASS | HTTP 200, count 81 |
| `/api/dcim/interfaces/` | PASS | HTTP 200, count 1105 |
| `/api/ipam/ip-addresses/` | PASS | HTTP 200, count 116 |
| `/api/virtualization/virtual-machines/` | DENIED | HTTP 403, count UNKNOWN |
| `/api/virtualization/interfaces/` | DENIED | HTTP 403, count UNKNOWN |
| `/api/extras/tags/` | DENIED | HTTP 403, count UNKNOWN |
| `/api/extras/custom-fields/` | DENIED | HTTP 403, count UNKNOWN |
| `/api/dcim/device-roles/` | PASS | HTTP 200, count 10 |
| `/api/dcim/platforms/` | PASS | HTTP 200, count 4 |
| `/api/dcim/sites/` | PASS | HTTP 200, count 3 |
| `/api/tenancy/tenants/` | PASS | HTTP 200, count 3 |

The devices collection exposed a next-page link; a second same-origin GET
returned HTTP 200 with the expected paginated shape. Denied datasets are
UNKNOWN, not zero. `raw/netbox-http-method-audit.txt` found 100 GETs, one prior
HEAD, and no POST/PATCH/PUT/DELETE API request from `192.168.1.91` in the
inspected log window.

Minimum missing view permissions:

- `virtualization.view_virtualmachine`
- `virtualization.view_vminterface`
- `extras.view_tag`
- `extras.view_customfield`

No NetBox permission, user, token, object, schema, or service was changed.

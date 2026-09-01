# M4 Permission Validation — PASS

Date: 2026-09-02

The existing encrypted NetBox credential resolves to principal
`topology-portal` and successfully read all four formerly denied resources:

| Resource | Required permission | HTTP | Count | Result |
|---|---|---:|---:|---|
| Virtual machines | `virtualization.view_virtualmachine` | 200 | 0 | PASS |
| VM interfaces | `virtualization.view_vminterface` | 200 | 0 | PASS |
| Tags | `extras.view_tag` | 200 | 0 | PASS |
| Custom fields | `extras.view_customfield` | 200 | 1 | PASS |

Devices, DCIM interfaces, IP addresses, roles, platforms, sites, and tenants
also passed in the subsequent full engine collection. The configured NetBox
origin remains `http://192.168.1.89`. No token value is present in evidence.

NetBox's nginx log audit inspected the latest 1,000 requests from
`192.168.1.91`: all were GET and none were POST, PUT, PATCH, or DELETE.

Raw evidence: `raw/permission-revalidation.txt` and
`raw/netbox-http-method-audit.txt`.

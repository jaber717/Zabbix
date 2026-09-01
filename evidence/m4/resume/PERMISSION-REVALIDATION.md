# M4 NetBox Permission Revalidation

Date: 2026-09-01

The operator reported granting these four read permissions to the existing
integration account:

- `virtualization.view_virtualmachine`
- `virtualization.view_vminterface`
- `extras.view_tag`
- `extras.view_customfield`

The credential already installed for the sync service was then revalidated
with GET requests only. No NetBox object, credential, user, permission, token,
configuration, or service was changed.

## Before/after matrix

| Resource | Required permission | Before resumption | After reported grant | Result |
|---|---|---:|---:|---|
| Virtual machines | `virtualization.view_virtualmachine` | HTTP 403 | HTTP 403 | DENIED |
| VM interfaces | `virtualization.view_vminterface` | HTTP 403 | HTTP 403 | DENIED |
| Tags | `extras.view_tag` | HTTP 403 | HTTP 403 | DENIED |
| Custom fields | `extras.view_customfield` | HTTP 403 | HTTP 403 | DENIED |
| Devices | existing view access | HTTP 200 | HTTP 200, count 81 | PASS |
| DCIM interfaces | existing view access | HTTP 200 | HTTP 200, count 1105 | PASS |
| IP addresses | existing view access | HTTP 200 | HTTP 200, count 116 | PASS |
| Device roles | existing view access | HTTP 200 | HTTP 200, count 10 | PASS |
| Platforms | existing view access | HTTP 200 | HTTP 200, count 4 | PASS |
| Sites | existing view access | HTTP 200 | HTTP 200, count 3 | PASS |
| Tenants | existing view access | HTTP 200 | HTTP 200, count 3 | PASS |

The after-state is evidenced by
`raw/netbox-permission-revalidation.txt`. The original before-state remains
preserved under `evidence/m4/raw/`.

## Conclusion

The four claimed permissions are not effective for the credential actually
presented by the installed sync service. The evidence does not establish why;
it does not prove whether the reported grant was attached to a different
principal, constrained away from the intended objects, or affected by another
permission rule. No account enumeration or permission mutation was attempted.

`REQUIRED_ENDPOINTS_COMPLETE=false`. M4 remains blocked before any Zabbix
credential provisioning or apply gate.

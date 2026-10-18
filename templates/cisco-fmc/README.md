# Cisco FMC by REST API — Zabbix 7.0 candidate

**Status: LAB CANDIDATE — NOT live validated.** Do not enable in production without a successful Zabbix import, a live FMC read-only API check, and an alert/recovery test.

## Files

- `zbx_template_cisco_fmc_rest_api.yaml`: self-contained importable candidate template (one Zabbix Script item, dependent items, discovery and triggers).

## Intended behavior

One script item queries FMC every five minutes using a dedicated monitoring account. It obtains an access token; discovers managed devices; requests version, pending deployment and health alerts; attempts token revocation; then returns a JSON document for Zabbix dependent items.

The script polls through the **Zabbix server/proxy** (not through the FMC host interface). Managed-device health from FMC is **not a replacement for FTD interface utilization**; use SNMP or the appropriate FTD telemetry source for interface in/out rates and errors.

## Important changes from the initial draft

1. Map `CRITICAL` to red and `WARNING` to yellow when reading Cisco Health Alerts. Cisco API samples use those values; the original collector only counted `RED` / `YELLOW` / `ERROR` / `FAILED`.
2. Reject a missing/non-array `items` response instead of interpreting it as an empty healthy collection.
3. Fail the affected section if the 20-page safety limit is reached with a full last page; never silently report a partial fleet count as complete.

The changes above passed **4 local mocked collector scenarios**: critical/warning alerts, later recovery, malformed primary response, and pagination-limit protection. These mocked tests do **not** establish FMC firmware compatibility, Zabbix 7.0 import compatibility, TLS trust, RBAC or live performance.

## Install/validation

1. Download the YAML from this branch or check out the branch in a connected LAB environment.
2. In Zabbix 7.0, go to **Data collection → Templates → Import**, import the YAML and inspect import errors. Do not enable an untested production host.
3. Create a dedicated FMC REST API monitoring user with only required read privileges, including Health Events if health alerts are desired.
4. Enable FMC REST API. Ensure the Zabbix polling server/proxy can resolve and reach the FMC HTTPS endpoint and trusts its server certificate. The Zabbix host's DNS connection address must match the certificate.
5. Add a host with a DNS interface set to FMC's certificate name; link `Cisco FMC by REST API`.
6. Set host macros `{$FMC.USERNAME}`, `{$FMC.PASSWORD}` (secret), and optionally `{$FMC.DOMAIN.UUID}`. **Never commit any credentials, tokens, production hostnames or returned FMC inventories to this public repository.**
7. Test **Cisco FMC: Get data** manually with the host disabled from scheduled collection. Confirm `ok=1` and verify discovered device counts and health states against FMC.
8. Confirm `fmc.warnings.count=0` (or investigate the failing section). Verify alerts, deployment and version paths against the **actual FMC firmware** before enabling alert actions.
9. Turn on collection in LAB and test degradation/recovery. Verify unknown/disabled health, empty lists, HTTP 401/403/429, API timeouts, trigger recovery and stale data.
10. Only after live acceptance, plan production deployment and rollback. If production lacks GitHub access, export or transfer the reviewed YAML through the approved offline workflow.

## FMC endpoints used

- POST `/api/fmc_platform/v1/auth/generatetoken`
- GET `/api/fmc_config/v1/domain/{domainUUID}/devices/devicerecords`
- GET `/api/fmc_platform/v1/info/serverversion`
- GET `/api/fmc_config/v1/domain/{domainUUID}/deployment/deployabledevices`
- GET `/api/fmc_config/v1/domain/{domainUUID}/health/alerts`
- POST `/api/fmc_platform/v1/auth/revokeaccess` (best effort)

The last four endpoint field shapes/permissions may vary by version and are **not yet verified against the target FMC**. Confirm with the actual firmware API explorer before calling this live-ready.

## Useful references

- [Zabbix 7.0 Script item](https://www.zabbix.com/documentation/7.0/en/manual/config/items/itemtypes/script)
- [Zabbix 7.0 JavaScript objects](https://www.zabbix.com/documentation/7.0/en/manual/config/items/preprocessing/javascript/javascript_objects)
- [Cisco Health Alert API documentation](https://developer.cisco.com/docs/fmc-ansible/gethealthalertmodel/)

# Cisco FMC by REST API — Zabbix 7.0 candidate

**Status: LAB CANDIDATE — NOT live validated.** Do not enable in production without a successful Zabbix import, a live FMC read-only API check, and an alert/recovery test.

## Files

- `zbx_template_cisco_fmc_rest_api.yaml`: self-contained importable candidate template (one Zabbix Script item, dependent items, discovery and triggers).

## Intended behavior

One script item queries FMC every five minutes using a dedicated monitoring account. It obtains an access token; discovers managed devices; requests version, pending deployment and health alerts; attempts token revocation; then returns a JSON document for Zabbix dependent items.

The script polls through the **Zabbix server/proxy** (not through the FMC host interface). Managed-device health from FMC is **not a replacement for FTD interface utilization**; use SNMP or the appropriate FTD telemetry source for interface in/out rates and errors.

## Changes in this revision (pagination + HTTP 403 fix)

Reported against FMC 7.6.6 / Zabbix 7.0.30: `deployabledevices: HTTP 403 - The user is not authorized.` and `health/alerts: pagination safety limit reached`.

**Pagination (`health/alerts`, also devices and deployments).** The old loop stopped only when a page held fewer records than the *requested* size, ignored the `paging` object, and gave up after 20 pages even if that page was the real last one, with no numbers in the error. It now:

- advances `offset` by the records actually received (a server that clamps `limit` is still read fully) and treats a page shorter than `paging.limit` (or an empty page) as the end;
- uses `paging.count` only as a cross-check: a list that ends before the reported count is an error (`incomplete list: read X of Y`), never a smaller result;
- detects a server that ignores `offset` (identical first/last records on consecutive pages) and stops after two pages instead of counting duplicates;
- refuses lists larger than `{$FMC.PAGING.MAX.ITEMS}` (default 50000) *before* fetching them, and caps a list at 50 pages / a poll at 100 calls (FMC allows 120/min), with the reported count, page size and page count in the message;
- treats a response with `paging` but no `items` as an empty list, and one with neither as an unexpected shape;
- streams alerts into a per-device/module/name "newest wins" map instead of holding every record.

What the live FMC actually does (more than 20 000 alerts in the window? offset ignored?) is not known from here; the new error text now says which. If you still see a pagination error, the message contains the count, page size and pages: reduce `{$FMC.ALERTS.WINDOW}` (e.g. 3600-14400) rather than raising the caps.

**Alerts are two independent sections.** The all-devices list (`alerts.all.*`) and the FMC-appliance list (`alerts.fmc.*`, `deviceUUID` 0). If the all-devices list fails or is too large, a narrow `deviceUUIDs:0` query keeps the FMC appliance alerts working (the filter syntax is **unverified**; results are also filtered client-side). `{$FMC.ALERTS.ALL.ENABLED}=0` runs only the narrow query.

**HTTP 403 on `deployabledevices`** is an FMC authorization response, not a template defect: the request is a plain authenticated GET of a documented resource, and the same token succeeds on devicerecords. The monitoring user's role does not include deployment access. Cisco's role documentation lists Administrator, Network Admin and Security Approver as roles that may deploy; read-only analyst roles cannot. I found no Cisco statement naming the exact privilege of this one endpoint, so confirm on your FMC. Either give the monitoring user a role that can view deployments (weigh this: those roles can also deploy) or set `{$FMC.DEPLOY.ENABLED}=0`; the pending-deployment items then simply stop updating. With the macro at 1 the 403 stays visible as a warning, a section status of *Forbidden* and an INFO trigger.

**Failure isolation.** Every API call is its own section. A failing section is omitted from the data (never zero-filled), its HTTP status and FMC message are published (`sections.<name>`, items `Collector section status, ...`, `Collector warnings`), and the others are still collected. Even a failing `devicerecords` now sets `ok=0` + error without discarding version, deployment and alert data. Authentication failures still throw (`AUTH:`) so a bad password is not retried at the normal rate.

New macros: `{$FMC.DEPLOY.ENABLED}` (1), `{$FMC.ALERTS.ALL.ENABLED}` (1), `{$FMC.PAGING.MAX.ITEMS}` (50000). New items: five `fmc.section.*` status items (value map *Cisco FMC collector section status*). New triggers: FMC appliance alerts not collected (WARNING), pending deployments not collected (INFO). Master item timeout 60 s -> 120 s. All earlier items, discovery, triggers and macros are unchanged.

Earlier changes: `CRITICAL`/`WARNING` alert statuses map to red/yellow; a missing/non-array `items` without `paging` is rejected rather than read as an empty healthy list.

## Offline tests (no FMC, no Zabbix server)

`node tests/test_collector.js` runs the collector embedded in the YAML against 23 mocked scenarios: the original 11 (paging past 100 devices, 401/403/429, size cap, header variants, revoke) plus honest paging over 5 pages, a server clamping `limit` to 25, offset ignored, a count of 200 000, count/list mismatch, missing `items`, an exactly-full last page, page/request budgets, the 403 on deployabledevices, deploy disabled, FMC-only alerts, and an empty fleet. The mocks follow Cisco's published response shapes; they do **not** establish FMC firmware compatibility, Zabbix import compatibility, TLS trust, RBAC or live performance.

## Install/validation

1. Download the YAML from this branch or check out the branch in a connected LAB environment.
2. In Zabbix 7.0, go to **Data collection → Templates → Import**, import the YAML and inspect import errors. Do not enable an untested production host.
3. Create a dedicated FMC REST API monitoring user with only required read privileges, including Health Events if health alerts are desired. Pending-deployment data (`deployabledevices`) needs a role that may view deployments, otherwise HTTP 403; see above and `{$FMC.DEPLOY.ENABLED}`.
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

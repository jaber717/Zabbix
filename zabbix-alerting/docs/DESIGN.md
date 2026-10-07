# Design, decisions and validation status

## Architecture

```
config/interfaces.yaml ──► config.py (strict YAML, typo/duplicate protection)
                              │ desired state
config/environments/*.yaml ─► envsafety.py (identity, URL guards, production gate)
                              │
                  planner.py ◄── ZabbixClient (read-only) ◄── Zabbix 7.0 API
                              │ plan = ADD / CHANGE / REMOVE + checks + conflicts
                  apply.py ───► ZabbixClient (write)  ──► configuration.import, usermacro.*,
                              │                            host.massadd/massremove, action.*, task.create
                  backup.py   (managed objects → state/backups before every apply)
```

Zabbix gets three kinds of objects, all supported API objects, all created by this tool and recognisable as its own:

1. **Template `NETOPS Interface Alerting`** — static, contains no interface name. One SNMP LLD rule `netops.if.discovery`
   filtered by regex macro `{$NETOPS.IF.MATCH}`, nine item prototypes (status, HC in/out octets, ifHighSpeed, effective
   capacity, in/out errors, in/out discards) and 28 trigger prototypes (7 alert types × 4 severities).
2. **Host user macros** `{$NETOPS.*}` — what the YAML becomes: the selection regex, and per-interface *context* macros
   `{$NETOPS.UTIL.MAX:"Gi0/0"}`. This is how "per-interface thresholds" work without per-interface templates.
3. **Action `NETOPS-IaC …`** (optional, only if the environment file defines `alert_action`) — filters on the event tag
   `netops_alert`, sends the rich message to named user groups through the media the group already has.

Per-interface severity: a trigger priority is fixed in a prototype, so each alert type exists once per severity and
is switched on by `{$NETOPS.SEV:"<if>"}=<2..5>`. Exactly one variant is active for an interface (tested).

Unselected interfaces keep being monitored by the stock templates; nothing here touches their LLD rules or items.

## Challenged assumptions (what changed from the brief and why)

| Topic | Decision |
|---|---|
| **Link DOWN "immediate"** | Polling-based: reaction time = poll interval of the status item (10 s by default for selected interfaces). SNMP traps would be faster but need device configuration, a trap receiver path and a polling fallback anyway (a lost trap = a missed outage). **Traps are deferred** — no router is touched in this phase. |
| **Utilization** | `last(rate) × 100 > threshold × last(capacity)`: newest sample only, no `avg/min` window, **no division** (a 0 speed cannot raise an error). Recovery uses a separate lower threshold (hysteresis); between 65 and 70 % an open problem stays open. |
| **Counters** | 64-bit `ifHCInOctets/ifHCOutOctets` with `CHANGE_PER_SECOND` then `×8`. 32-bit counters wrap in ≈ 34 s at 1 Gbit/s so they would be wrong at the polling rates asked for and unusable above 4 Gbit/s. |
| **Capacity** | `ifHighSpeed` (Mbit/s, correct for > 4 Gbit/s links where `ifSpeed` saturates at 4.29 G). `expected_speed` overrides it (needed for LAG bundles and devices that report a wrong speed) and drives the speed-degradation alert. |
| **10 s polling** | Applies only to *selected* interfaces. Per interface: 3 values every 10 s (status, in, out) + 6 every 60 s ≈ **0.40 new values/s** and ≈ 0.38 SNMP GETs/s. 40 critical interfaces ≈ 16 values/s; one device with 8 critical interfaces ≈ 3 GETs/s. Zabbix may merge OIDs of one device into combined requests. `--check` prints this estimate. Re-check the poller busy rate after rollout. |
| **Counter-based rates need two samples** | Utilization/error rates exist from the second poll after (re)discovery. Intentional. |
| **Reuse of stock templates** | The stock "Interfaces SNMP" LLD is host-wide, polls every 3 min through a walk and uses `avg(15m)>90 %` / `min(5m)`-style triggers — it cannot be made immediate per interface without changing it for everyone. Reusing it would also change every existing host. So: own template for selected interfaces, stock untouched. Optional `suppress_stock: true` sets the stock gating macro `{$IFCONTROL:"<if>"}=0` for selected interfaces to avoid duplicate stock alerts (off by default). |
| **YAML → context macros vs tags** | Macros carry numbers/strings (thresholds, severity, description). Tags carry what the *action* needs to route/format (`netops_alert`, `if_name`, `role`, `site`, …). Severity is a variant switch, not a tag, because priority is static in a prototype. |
| **Flapping** | Detected with `changecount()` on the status item; the link DOWN trigger depends on it so a bouncing link yields one problem. Trade-off documented in the README (a persistent outage after flapping is announced when the flap window closes). |
| **LAG** | Member and bundle interfaces are ordinary interfaces; a bundle's `ifOperStatus` reports "up" while degraded on several platforms, so **bundle-degradation (fewer members up) is not reliably detectable from standard IF-MIB** and is not claimed. Alert on the members (`link_alert`) and set `expected_speed` on the bundle (capacity drop → speed alert) where the platform reports aggregate speed. |
| **Vendors** | IF-MIB `ifOperStatus`, `ifHC*`, `ifHighSpeed`, `ifInErrors/ifInDiscards` are standard and implemented on Cisco IOS/IOS-XE/IOS-XR/NX-OS, Huawei VRP, Palo Alto PAN-OS and F5 TMOS. Expected caveats (from general platform behaviour, not measured here): some virtual/aggregate interfaces (PAN-OS, F5, LAGs) may report speed 0 (the tool then neither divides nor alerts on utilization — set `expected_speed`); NX-OS and IOS-XR report `ifDescr` long names (use the exact name shown in Zabbix); counters on some virtual platforms may be 32-bit only (items go unsupported — surfaced by `lab_verify_objects.py`). None of this has been proven on real devices in this phase. |
| **Interface existence check** | Interface names are taken from the `interface` tag of the host's existing stock items. A host without that tag cannot be verified and fails `--check` (fail closed). |

## LAB → PRODUCTION

Nothing environment-specific is in code or in the template: no URLs, IPs, ids, tokens or paths. Objects are found by
name/key/tag. Per environment only `config/environments/<env>.yaml` and two environment variables differ.

* `--env` selects the file; the file must declare the same name. Variables are read **only** from the names the file lists (no fallback to another environment's variables).
* Identity is proven by the server, not by the URL (see README). A LAB invocation against a server that says `production` is refused.
* Production requires `url_regex` in its file (the shipped value is a placeholder that matches nothing: **fail closed until set**), prints a banner (environment, URL, API version, counts), and writes only with `--confirm production`.
* Drift: `--dry-run` compares live managed objects with Git and reports `CHANGE … live '80' -> git '70'`; template drift (missing/extra prototypes, repository version) is detected by comparing live prototypes with the generated template.
* Before every apply the managed objects (not the whole Zabbix) are written to `state/backups/`.

## Phase B (P2P interface handover)

`handover/CLAUDE-HANDOVER.md` and `handover/p2p-interfaces.yaml` (from Codex) do not exist yet, so **no production interface list is assumed**
and `config/interfaces.yaml` holds only a LAB starter policy. When they arrive:

```bash
./scripts/ingest-handover.py handover/p2p-interfaces.yaml --env lab   # read-only; verifies every entry live
#  → config/interfaces.generated.yaml (verified only) + REVIEW-REQUIRED.md (everything that did not verify)
```

Review, copy into `config/interfaces.yaml`, then `--check`, `--dry-run`, apply.

## Validation status

**PASS WITH LIMITATIONS.** Framework implementation and offline API tests passed, but real Zabbix mutation/apply validation
is pending because the current service account is read-only.

What was proven where:

| Evidence | Where | Covers |
|---|---|---|
| Unit/integration tests (`python3 -m unittest discover -s tests -t .`) | in-memory model of the Zabbix 7.0 API, real CLI/planner/applier/client code | YAML validation, plan/dry-run/apply, create/update/delete decisions, ownership protection, drift, idempotency, utilization newest-sample + hysteresis, flapping/link behaviour on the generated expressions, environment separation, production gates, read-only client guard |
| `scripts/live-readcheck.py` | **live LAB Zabbix 7.0.30, read-only** (via the Grafana datasource proxy) | host lookup, SNMP-interface check, real interface names from item tags, typo/case/missing-host failures, ownership scan, API version, identity macro read |
| `scripts/lab-write-test.sh` | **not yet run** — needs a write-capable LAB token | `configuration.import` acceptance of the template, real macro/link/action writes, real LLD discovery, real values, real trigger evaluation, idempotent second run |

Things the offline model cannot prove and that the first real run must confirm: that Zabbix 7.0.30 accepts the generated
template on import (key names such as `lifetime_type`, trigger dependency format, preprocessing parameter layout), that the
trigger expressions/`event_name` macros compile, that discovery produces supported items on the target platforms, and
that `host.massremove … templateids_clear` and `task.create` behave as modelled, that Zabbix expands the user macro inside the capacity item's JavaScript preprocessing (otherwise `expected_speed` would not override the reported speed for utilization), and that the server does not reformat trigger expressions in a way that shows up as permanent template drift (whitespace is already ignored). `lab-write-test.sh` checks each of these and
`lab_verify_objects.py` reports unsupported items.

Once a write-capable LAB token is in `.env`:

```bash
./apply.sh --env lab --check
./apply.sh --env lab --dry-run
./apply.sh --env lab
./apply.sh --env lab --dry-run       # → "No changes required."
./scripts/lab-write-test.sh          # all of the above plus change/revert/discovery/values/removal on a harmless policy
```

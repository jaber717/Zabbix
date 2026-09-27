# Network Availability v1

This directory is a Zabbix 7.0 frontend widget module. It is an incremental,
implementation of platform-neutral Site, Node and Member availability. Release
`1.2.1` keeps the tested collector/resolver authoritative while refining the
NOC presentation and persistent Site/Node editor. Availability color and
monitoring visibility are separate. Needs Attention uses native Zabbix problem
acknowledgement, never browser-local acknowledgement state. KPI filters apply
to incidents and Site/Node presentation. An unset Tier is visibly “No tier”
and retains resolver-assigned P? priority; a configured Node still requires an
explicit Tier when saved.

## Model and configuration

The runtime configuration is authoritative for Site assignment, display name,
Tier, Node membership, kind, aggregation policy, MIN_N, ordering, and hidden
card state. Host Tags and Groups are read-only suggestions and are never
silently promoted into configuration.

Logical Nodes live outside the module source tree in
`/var/lib/zabbix/network-availability/node-definitions.json`. The installer
creates the least-privilege runtime store and an initial last-known-good copy.
Writes are validated, revision-checked, locked, and atomically renamed. The
repository default remains empty; `config/node-definitions.example.json` is a
fake, non-production example. The schema has this shape:

```json
{
  "schema": "network-availability-config-v2",
  "revision": 1,
  "sites": [{"id": "dc-01", "name": "DC-01", "order": 10}],
  "nodes": [
    {
      "id": "dc01-internet-edge",
      "name": "Internet Edge",
      "site_id": "dc-01",
      "kind": "logical_service",
      "aggregation_policy": "MIN_N_REQUIRED",
      "min_n": 1,
      "criticality": "tier1",
      "order": 10,
      "hidden": false,
      "description": "Example only",
      "members": [
        {
          "id": "stc",
          "name": "RTR-01 / STC",
          "host": "RTR-01",
          "availability_item_key": "icmpping",
          "expected_interval_s": 60,
          "availability_source": "ICMP"
        },
        {
          "id": "mobily",
          "name": "RTR-02 / Mobily",
          "host": "RTR-02",
          "availability_item_key": "icmpping",
          "expected_interval_s": 60,
          "availability_source": "ICMP"
        }
      ]
    }
  ]
}
```

The same Host may appear in multiple Node definitions. `MAJORITY_REQUIRED` on a
two-Member Node is rejected unless `allow_two_member_majority` is explicitly
true. `CUSTOM` is not implemented.

A visible monitored Host absent from Node definitions becomes **Unassigned**.
Its Tier remains unset and incidents display `P?`; the system never fabricates
Tier-3. Unknown-Tier outages rank above known low-priority Tier-3 incidents.

## Freshness

The selected availability item supplies the raw value and `lastclock`.
`ExpectedIntervalResolver` accepts a positive Member-level
`expected_interval_s`, or a straightforward fixed item delay after asking the
Zabbix macro resolver to expand time-unit macros. Flexible, scheduled,
unresolved, or otherwise ambiguous intervals fail visibly. The implementation
does not invent a default interval.

## Query plan

Each refresh uses bounded bulk reads under the current Zabbix user's RBAC:

1. one `host.get` for monitored Hosts and classification tags;
2. one `item.get` for only configured/default availability keys;
3. one history read per selected value type for the flap window (normally one
   unsigned-numeric read for the built-in binary availability keys);
4. one `trigger.get` for active trigger dependencies; and
5. one `problem.get` for active problem overlays.

History queries are bounded by Zabbix's finite set of item value types, not by
Host, Member, or Node count. There is no per-Host, per-Member, or per-Node API
loop. Services are not queried
in v1 and never override Member-derived truth. The collector returns normalized
Nodes/Members plus instrumentation; the resolver has no Zabbix API dependency,
so a future short-lived cache can be inserted between them.

Debug mode exposes API call count, Hosts retrieved, Members resolved, Nodes
resolved, Problems retrieved, collector time, resolver time, and total widget
time. The widget refresh is 30 seconds and never below the central 10-second
floor.

## Lab validation status

On 2026-09-22 this module was installed and enabled in the lab Zabbix 7.0.30
frontend at `/usr/share/zabbix/modules/NetworkAvailability`. Live validation
covered manifest/class loading, authenticated bulk API calls, controller
rendering, summary/Site/Node/configuration-debt output, Hero continuity, TLS,
service health, and recent PHP/nginx/SELinux errors.

The repository subdirectories `collector`, `config`, and `domain` are lowercase
because the Zabbix module autoloader lowercases nested namespace paths on the
case-sensitive RHEL filesystem.

The central Node definition was intentionally empty during v1.0 validation. All
five current lab Hosts therefore rendered as **Unassigned**;
the four NetBox mock devices report their expected DOWN signals while
`ZABBIX-01` reports UP. This is lab validation, not production Node modeling or
real-device polling acceptance. Do not deploy this module to production until
production Node definitions, operator RBAC, load, and real monitoring sources
have been reviewed.

## Tests

Run the pure-PHP resolver matrix:

```bash
php tests/availability/run.php
php tests/availability/config_test.php
```

Run the repository/static contracts:

```bash
python3 tests/availability/static_test.py
```

Production operators should follow `docs/NETWORK-AVAILABILITY-PRODUCTION.md`.
The installer preserves the external runtime configuration during upgrades and
rollbacks and validates all immutable module files against `RELEASE.sha256`.

# Network Availability v1

This directory is a Zabbix 7.0 frontend widget module. It is an incremental,
read-only implementation of platform-neutral Site, Node and Member availability.
Release `1.0.2` adds production-safe installation, verification, and rollback
tooling without changing the validated widget behavior.

## Model and configuration

Host Tags classify candidates. V1 consumes `site`, `criticality`, and
`availability_source_id`; `role` and `platform` remain classification metadata
for future discovery/presentation without becoming hard-coded vendor policy.
The collector does not derive logical Node membership or aggregation policy
from independent Host Tags.

Logical Nodes live in the centrally shared
`config/node-definitions.json`. The repository default is intentionally empty.
`config/node-definitions.example.json` is a fake, non-production example. A
definition has this shape:

```json
{
  "schema": "network-availability-node-definitions-v1",
  "nodes": [
    {
      "id": "dc01-internet-edge",
      "name": "Internet Edge",
      "site": "DC-01",
      "kind": "logical_service",
      "aggregation_policy": "MIN_N_REQUIRED",
      "min_n": 1,
      "criticality": "tier1",
      "order": 10,
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

A visible monitored Host absent from Node definitions becomes a single-Member
`UNCLASSIFIED` card. Its availability truth is still resolved, but its kind and
production policy are not fabricated. The card lists missing Site/Node mapping
as configuration debt.

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

The central Node definition remains intentionally empty. All five current lab
Hosts therefore render as visibly configuration-required under `UNCLASSIFIED`;
the four NetBox mock devices report their expected DOWN signals while
`ZABBIX-01` reports UP. This is lab validation, not production Node modeling or
real-device polling acceptance. Do not deploy this module to production until
production Node definitions, operator RBAC, load, and real monitoring sources
have been reviewed.

## Tests

Run the pure-PHP resolver matrix:

```bash
php tests/availability/run.php
```

Run the repository/static contracts:

```bash
python3 tests/availability/static_test.py
```

Production operators should follow `docs/NETWORK-AVAILABILITY-PRODUCTION.md`.
The installer preserves an existing `config/node-definitions.json` during an
upgrade and validates all immutable module files against `RELEASE.sha256`.

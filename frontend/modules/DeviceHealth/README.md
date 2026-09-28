# Device Health & Capacity

Zabbix 7.0 widget for trigger-led resource, hardware, environmental, storage and HA health. Zabbix problems are the only source of Warning/Critical severity. Raw metrics without a mapped trigger remain neutral.

Runtime paths:

- `/var/lib/zabbix/device-health/device-health.json`: capability/profile and storage-rollup policy.
- `/var/lib/zabbix/device-health/first-observed.json`: persistent no-data grace timestamps.

Freshness is evaluated per metric item using that item's effective update interval and the same three-interval policy as Network Availability. Dependent items inherit the update interval of their master item. No metric borrows the Availability timestamp.

The initial LAB policy includes `/` and `/home` in the storage rollup. `/boot` remains visible in Details but is excluded from the main rollup because its operational relevance was not explicit in the current templates. The runtime configuration is operator-editable outside source control.

Pinned historical trends are intentionally deferred from v1.0.0. The core matrix, normalized Needs Attention list and Details inspector do not add history/trend API calls.

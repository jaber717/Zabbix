# NETOPS Hardware Health (independent project)

**Status: v0.1 discovery / coverage audit. NOT a Production alerting release.**

Separate from the frozen zabbix-alerting/v1.0.2 interface project.

## Goal

Detect fan failures, PSU failures, temperature alarms, hardware redundancy loss,
and missing/stale sensor monitoring. Reuse verified official/vendor templates and
their triggers before creating vendor-specific templates.

## Current functionality

- Read-only Zabbix 7.0 API inspection of explicitly selected hosts.
- Distinguishes present sensor items, enabled hardware triggers, and fresh supported
  values. Never treats "no sensor available" as healthy.
- Reports per-host category gaps, available event tags, template names and example triggers.
- Strict LAB vs Production policy and separate API credentials.
- No direct DB writes, no SNMP device changes, no modifications to
  zabbix-alerting, no automatic tagging of stock templates.
- Exit 0 when all required categories are covered, 2 on coverage gaps,
  3 if the audit cannot be trusted.

## Initial setup (LAB only)

From Zabbix/zabbix-hardware-health:

    python3 -m pip install -r requirements.txt
    python3 -m unittest discover -s tests -v

Edit config/hardware.lab.yaml with the exact Zabbix host names, the
expected categories for each device and sensor freshness limits.
Do NOT list unsupported components as healthy; document exceptions
explicitly in acceptance evidence.

Set credentials only in the session or a protected secrets store:

    export ZABBIX_HARDWARE_URL_LAB=https://your-zabbix-frontend
    export ZABBIX_HARDWARE_TOKEN_LAB=your-api-token

Run:

    python3 hardware_audit.py --env lab --output hardware-report.json

Do not commit the report if it contains sensitive device metadata.

## Notifications — future acceptance stage

The audit is **not** an alert sender. Zabbix's existing enabled
hardware triggers will be the source of Problems and Recoveries.

After reviewing real trigger tags, configure a separate Zabbix Action
named NETOPS Hardware Health with a dedicated operator group and
Email/Telegram media. Scope its filters to confirmed hardware-event tags
and device groups; DO NOT use a broad host-group-only rule or blindly
assume that every stock template shares the same event tags.

The independently tested LAB action must deliver Fan problem/recovery,
PSU problem/recovery, and temperature problem/recovery; it must not
send interface-alert or unrelated events. Current scope is discovery,
not live notification deployment.

See docs/ACCEPTANCE.md for required testing and vendor coverage.

## Limitations

- Matching item/trigger names provides a candidate inventory, not proof
  that vendor OID values have the same semantics.
- Freshness cannot be proven by a missing data point. Template-specific
  heartbeat intervals must be validated (some stock items are infrequent).
- Sensors without dedicated triggers, including redundancy, are reported
  as gaps. Vendor-specific monitoring is a separate vetted implementation.
- User groups, media types, auto-actions and device configuration are NOT
  created by this read-only v0.1 tool.
- No testing on the user's LAB or Production is claimed.
- Use a dedicated branch, never overwrite the v1.0.2 interface-alert tag.

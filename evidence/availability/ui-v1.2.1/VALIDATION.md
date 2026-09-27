# Network Availability v1.2.1 LAB validation

Date: 2026-09-27. Scope: isolated LAB Zabbix 7.0.30 / PHP 8.3.19 / RHEL 9.6. Production was not accessed.

## Real-browser visual validation

`tests/availability/ui_fixture.php` rendered the production PHP view with data resolved by the real `AvailabilityResolver`, then loaded the production CSS and JavaScript in headless Chrome. Blue/light and Dark passed at 1200, 1440, 1920, 2200, 900, 640 and 420 px.

Computed-layout assertions confirmed:

- the operational content column is centered and never exceeds 1480 px;
- KPI chips never exceed 175 px at 1440/1920/2200 px (configured width: 168 px);
- the Needs Attention action area never exceeds 1040 px and incident state remains within 1060 px of the row start;
- DOWN uses a computed 4 px severity border and a background distinct from a neutral visibility incident;
- healthy Node rows remain at or below 34 px at 1200/1920/2200 px;
- healthy single-member Nodes contain one availability dot, no `UP` text, and no Member glyph container;
- long names, badges, state, Details and editor controls do not overlap or cause page-level overflow;
- singular/plural rendering produces `1 item` and `2 items` from separately rendered production views.

Interaction coverage passed for native acknowledgement, affected Site collapse/reopen, healthy Site chip expansion, search, KPI filtering and clear, Details pairing/open/close, real edit diff tracking, Tier-not-set presentation, Save and Discard. Availability remains independent from monitoring visibility: the `UP + PARTIAL` fixture retained its green state dot and teal visibility badge.

Screenshots in this directory cover the main view in both themes at the desktop, ultrawide and narrow target widths, plus Details and editor presentations.

## Authenticated LAB validation

- Installer preflight, upgrade and verifier: PASS.
- Runtime configuration: preserved during upgrade and restored to empty revision 20 after the controlled validation exercise.
- Quick Assign-shaped save/refresh, Site rename, multi-member Node, reorder, hidden monitored Node, invalid-config rejection, Details/filter/search render contracts: PASS.
- Read-only credential: web login denied; no elevated session was obtained.
- No service restart was performed.

Performance on the same empty LAB configuration:

| Release state | API calls | Collector | Resolver | Total widget |
|---|---:|---:|---:|---:|
| v1.2.0 baseline | 5 | 37.076 ms | 0.777 ms | 39.120 ms |
| v1.2.1 final, post-restore | 5 | 35.272 ms | 0.730 ms | 37.042 ms |

The visual patch added no API calls and produced no meaningful server-side regression.

## Regression suites

- Availability resolver: 41 assertions PASS.
- Runtime configuration/persistence: 11 assertions PASS.
- Static, deployment, checksum, PHP lint and shell syntax contracts: PASS.
- Isolated installer smoke: preflight, read-only verifier and tamper rejection PASS.
- Network Utilization: 27 analytics assertions, persistence/configuration and static contracts PASS; no Network Utilization file changed.

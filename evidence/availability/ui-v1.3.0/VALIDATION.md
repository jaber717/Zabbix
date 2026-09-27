# Network Availability v1.3.0 validation

Date: 2026-09-27

Scope: Network Availability main-view layout only

Environment: LAB Zabbix 7.0.30, PHP 8.3.19, RHEL 9.6

Production access: none

## Real-browser validation

The fixture is rendered by the real `widget.view.php` using
`AvailabilityResolver` output and loads the production module CSS and
JavaScript directly. Google Chrome headless (`--headless=new`) exercised both
Blue/light and Dark themes at 2200, 1920, 1440, 1200, 900, 640, and 420 px.

PASS:

- 8 healthy Nodes form 3 columns at 2200/1920/1440 px, 2 columns at
  1200/900 px, and 1 column at 640/420 px.
- Healthy Node rows remain at or below 34 px and omit redundant UP text,
  duplicate state dots, and single-member glyphs.
- The affected Node is a separate full-width problem row below the healthy
  grid.
- Needs Attention has no overlap and remains bounded/cohesive at ultrawide
  widths.
- Site name, healthy count, and problem count share one header container.
- Search remains no wider than 480 px on desktop and fills the narrow toolbar.
- No page-level horizontal overflow at any tested width.
- Native acknowledgement, Site collapse/reopen, filters, search, Details,
  editor save/discard, Tier-not-set, visibility separation, maintenance, and
  flapping interactions pass.

The PNG files in this directory are the captured browser evidence.

## Functional and deployment validation

- PHP syntax: PASS
- Resolver suite: 41/41 PASS
- Configuration suite: 11/11 PASS
- Static contracts: PASS
- Deployment safety contracts: PASS
- Isolated preflight/install/verify/tamper rejection: PASS
- Release checksums: PASS
- Network Utilization source diff: none
- Network Utilization regression: 27 analytics assertions, configuration,
  persistence, performance, and static contracts PASS

## Live LAB validation

The exact checksum-locked v1.3.0 candidate was installed in LAB. The external
runtime configuration remained at revision 20 with zero configured Sites and
Nodes. Authenticated widget rendering returned HTTP 200 and the expected five
monitored Hosts. nginx and PHP-FPM remained active and no recent fatal/parse
errors were found.

- API calls: 5 (unchanged from v1.2.1)
- Collector: 36.493 ms
- Resolver: 0.809 ms
- Total server-side widget execution: 38.525 ms
- End-to-end authenticated widget request: 118.095 ms

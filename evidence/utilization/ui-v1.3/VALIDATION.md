# Network Utilization v1.3.0 LAB UI validation

The release candidate was installed and verified on the isolated RHEL 9.6 LAB Zabbix VM (Zabbix 7.0.30, PHP 8.3.19). No production system was accessed. The existing runtime Link configuration was preserved; the controlled one-link live exercise restored the original empty configuration afterward. The installer restarted no service.

## Browser release gate

- Live authenticated LAB browser: **NOT AVAILABLE**. The LAB uses a self-signed server certificate (`CN=zabbix-01.lab`, no separate CA identified). No TLS-verification bypass or machine-wide trust change was made.
- Real-browser component validation: **PASS**, Chrome/Chromium 153.0.8010.53. `tests/utilization/ui_fixture.php` renders the real module `views/widget.view.php` with synthetic Zabbix-shaped data and embeds the real module CSS and all three JavaScript assets. `tests/utilization/browser_test.js` drives that fixture through Chrome DevTools Protocol. This is a browser render of production components, not a hand-rewritten mockup.
- Blue/light and Dark at 1200, 900, 640 and 420 px: **PASS**. No page-level horizontal overflow or geometric attention-row collision. Inspector width, long-name containment and narrow Edit actions: **PASS**.
- Sort Current, P95, Remaining, Errors and Discards, descending and ascending: **PASS**. Search+sort, Site+sort and Role+sort: **PASS**. Browser tests assert actual DOM order, not a separate sorting implementation.
- Needs Attention badge/name/metadata/reason/summary structural separation, long alias title, paired inspector label/value rows, missing capacity and service capacity: **PASS**.
- Chart 1h/6h/24h/7d buttons, distinct time-window footer, axes, tooltip and crosshair: **PASS**.
- Edit Add Link, Discard and mocked Save handler/config result: **PASS**. This fixture save does not alter LAB runtime configuration.

Screenshots: `network-utilization-{blue,dark}-{1200,640,420}.png`, `network-utilization-sites-{blue,dark}-1200.png`, `network-utilization-details-{blue,dark}-{1200,420}.png`, and `network-utilization-editor-dark-{900,420}.png` in this directory.

## LAB and regression

- Installer preflight, installer, verifier, release checksums, PHP lint, static module checks: **PASS**.
- Utilization analytics (25 assertions), persistence/configuration, chart and capacity-config tests: **PASS**.
- Network Availability regression (41 analytics and 11 configuration assertions): **PASS**. Availability source was not changed.
- Authenticated live LAB validation: **PASS**. Rendered module 1.3.0; source Items `net.if.in["ens18"]` and `net.if.out["ens18"]`; native history/trend comparison **PASS**; symmetric 50 Mbps IN/OUT save/reload **PASS**; missing capacity and invalid zero capacity **PASS**; empty original runtime configuration restored.
- One-link measured widget instrumentation: 4 API calls, 1,011 history rows, 30 trend rows, collector 70.701 ms, analytics 0.687 ms, total 72.32 ms. This remains within the 100 ms target and does not increase API calls from the four-call baseline. Timing is a single LAB observation, not a latency guarantee.

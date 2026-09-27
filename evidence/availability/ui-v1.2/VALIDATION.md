# Network Availability v1.2.0 LAB validation

Date: 2026-09-27. Scope: LAB Zabbix 7.0.30 / PHP 8.3.19 on RHEL 9.6 only. No production access.

## Browser evidence

`tests/availability/ui_fixture.php` rendered the real module PHP view with data from the real `AvailabilityResolver`, then loaded the real module CSS and JavaScript in headless Chrome 153. `tests/availability/browser_test.js` passed the interaction and geometry assertions at 1200, 900, 640, and 420 px in Blue/light and Dark. It checked tier-unset ordering, hidden and unassigned outages, visibility/availability color separation, native Zabbix acknowledgement popup invocation, Site collapse/reopen, operational KPI filtering, search, Details pairing, real edit diff/save/discard, editor action containment at all four widths, and no text collision or horizontal overflow. Screenshots alongside this file show the tested views and editor.

The browser also reached the LAB TLS login page using `--ignore-certificate-errors` in that isolated test process only. This was a login-page smoke check, not an authenticated live-browser UI session. Authenticated LAB API/controller and module validation were performed separately. No production security setting was changed.

## LAB functional and deployment evidence

- Candidate release checksum validation: PASS (outer release and module manifests).
- PHP resolver: 41 assertions PASS; configuration: 11 assertions PASS.
- Static/deployment contracts: PASS; isolated preflight, read-only verifier, tamper rejection: PASS.
- LAB installer and verifier: PASS; runtime configuration preserved; no service restart.
- Authenticated LAB validation: PASS; 5 monitored Hosts, 5 snapshot Nodes, 4 Needs Attention incidents. Quick Assign, Site rename/multimember/reorder save, invalid-config rejection, hidden-node monitoring, and restore-to-empty PASS. Revision after restore: 17, Sites: 0, Nodes: 0.
- Healthy Site chip in the authenticated LAB run: not applicable because the LAB configuration was intentionally empty and all four NetBox mock Hosts report expected DOWN signals. Healthy Site chips and ordering were exercised in the real-browser fixture.
- Performance: baseline 5 API calls, collector 33.666 ms, resolver 0.69 ms, total 35.348 ms. Final installed artifact: 5 API calls, collector 34.815 ms, resolver 0.846 ms, total 36.701 ms. A second authenticated read-only validation after the final install passed with config still empty at revision 17.
- Network Utilization module unchanged. Its analytics (25 assertions), configuration/persistence, and static contracts passed.

The fixture and screenshots validate the browser-visible module components, while the authenticated LAB run validates live module integration. They should not be described as an authenticated live-browser visual pass.

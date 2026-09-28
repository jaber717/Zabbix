# Daily Reporting validation evidence

Date: 2026-09-28 (Asia/Riyadh)

## Scope

Validation used the existing RHEL 9.6 LAB Zabbix 7.0.30 server. No production system was accessed. No native-reporting package, browser, repository, firewall, SELinux, or Zabbix server configuration was changed.

## Custom report — PASS

- Authenticated to the live Zabbix API over its existing TLS endpoint using a credential injected only into the process environment.
- Generated previous-day JSON and HTML for `2026-09-27T00:00:00+03:00` through `2026-09-28T00:00:00+03:00`.
- Verified all intended exception sections exist.
- Seven bounded API calls were used for the five-host LAB scope, including a dedicated previous-day recovery-event query so resolutions are not limited to problems that also began yesterday.
- No email was sent.
- Sanitized summary: [lab-custom-report-summary.json](raw/lab-custom-report-summary.json).

## Native scheduled PDF — prerequisite blocked

The read-only privileged preflight returned exit code 2 (`WARNING`), not an implementation failure. The LAB currently lacks:

- `zabbix-web-service` RPM
- Chrome/Chromium executable
- `WebServiceURL=.../report`
- positive `StartReportWriters`
- `/etc/zabbix/zabbix_web_service.conf`

The Zabbix Frontend URL is also empty, and no scheduled report or active recipient email media currently exists. The plan-only API helper successfully read dashboard `57`, current settings, and scheduled-report state without changing them. Raw prerequisite evidence: [lab-native-preflight.json](raw/lab-native-preflight.json).

## Automated and deployment checks — PASS

- Python unit tests: 5/5 PASS.
- Static/safety contracts: 4/4 PASS.
- Python compilation: PASS.
- Bash syntax: PASS on RHEL 9.6.
- `shellcheck`: NOT AVAILABLE in the development workstation or LAB; Bash parser validation was used and this limitation is retained.
- Isolated-root installer: PASS.
- Isolated-root verifier: PASS with expected native PDF warning and expected missing-credential warning.
- Rollback: PASS; operator configuration and report state preserved.
- Offline archive SHA256: PASS.
- Extracted `MANIFEST.sha256`: PASS.
- Installer/verifier/rollback executed again from the extracted archive: PASS.
- Network Availability: 41 PHP assertions and static contracts PASS.
- Network Utilization: 27 PHP assertions and static contracts PASS.
- Network Availability and Network Utilization paths: no diff.

## Security checks

- TLS verification remained enabled.
- No credentials were written to evidence, Git, generated report summaries, or the bundle.
- No SELinux/firewalld/TLS weakening exists in the installer.
- Native server changes require both `--apply-native-config` and passing prerequisites/config validation.
- Timer enablement refuses to proceed without protected API credentials.

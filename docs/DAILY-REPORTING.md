# Zabbix Daily Reporting

Version `1.0.0-rc1` provides two deliberately independent reporting paths:

1. A configuration-driven Python report that reads Zabbix 7.0 API data and writes bounded previous-day JSON and HTML summaries.
2. Native Zabbix Scheduled PDF preparation, prerequisite detection, and an explicit API apply step.

The custom report does not require `zabbix-web-service` or a browser. Native PDF generation does.

## Architecture

```text
Zabbix API -> zabbix_daily_report.py -> HTML + JSON -> optional SMTP
Zabbix dashboard -> zabbix-server report writer -> zabbix-web-service + Chrome -> native PDF email
```

The source lives under `reporting/daily-reporting/`. Production state is separate:

- Application: `/opt/zabbix-daily-reporting`
- Configuration: `/etc/zabbix-daily-reporting/report.json`
- Protected credentials: `/etc/zabbix-daily-reporting/secrets.env` (`0600`)
- Reports/state: `/var/lib/zabbix-daily-reporting`
- Backups: `/var/backups/zabbix-daily-reporting`

No credential belongs in Git or in the offline archive.

## Offline deployment

On the connected workstation:

```bash
git switch codex/daily-reporting
git pull --ff-only
./scripts/build_offline_bundle.sh
(cd dist && sha256sum -c zabbix-daily-reporting-1.0.0-rc1.tar.gz.sha256)
```

Transfer the archive and its `.sha256` file through the approved offline process. On the isolated RHEL 9 server:

```bash
sha256sum -c zabbix-daily-reporting-1.0.0-rc1.tar.gz.sha256
tar -xzf zabbix-daily-reporting-1.0.0-rc1.tar.gz
cd zabbix-daily-reporting-1.0.0-rc1
sudo ./scripts/install_daily_reporting.sh --preflight
sudo ./scripts/install_daily_reporting.sh
sudo ./scripts/verify_daily_reporting.sh
```

The default install does not enable the timer and does not alter `zabbix_server.conf`. Configure the files below first.

## Configuration

Edit `/etc/zabbix-daily-reporting/report.json` as root. Every field is described here.

### `report`

- `name`: display/email title.
- `period`: must be `previous_day` in v1.
- `schedule_local`: daily `HH:MM` timer/native-report start time.
- `timezone`: IANA timezone used for day boundaries.
- `output_directory`: HTML/JSON destination.
- `retention_days`: age after which generated report files are removed.

### `zabbix`

- `api_url`: full `api_jsonrpc.php` URL.
- `frontend_url`: externally reachable HTTPS frontend URL used by native reports.
- `ca_file`: trusted CA/certificate path; TLS verification is never disabled.
- `request_timeout_seconds`: API timeout.
- `maximum_hosts`, `maximum_items`, `maximum_problems`: bounded API safety limits.

### `scope`

- `sites`: allowed site tag/group values; empty means all monitored hosts.
- `site_tag`: host-tag key used for site grouping.
- `include_host_groups`, `exclude_host_groups`: optional exact group filters.

### `severity`, `thresholds`, and `classification`

- `severity`: current problem severities included in the High/Disaster section.
- `cpu_percent`, `memory_percent`, `interface_utilization_percent`: configurable values.
- `stale_data_minutes`: age of the newest enabled item used for stale-device reporting.
- `flapping_events`: previous-day downtime events required to classify a device as flapping.
- `raw_metric_evaluation`: default `false`. When false, CPU/memory values are not assigned frontend-invented severity; validated Zabbix problems remain authoritative.
- `*_problem_patterns`: case-insensitive problem-name classifications for downtime, utilization, and HA sections.

### `delivery`

- `custom_email_enabled`: enable direct SMTP for the custom HTML report.
- `recipients`: email address list.
- `smtp_host`, `smtp_port`, `smtp_starttls`, `smtp_username`, `sender`: SMTP parameters.
- SMTP password is read only from `DAILY_REPORT_SMTP_PASSWORD`.

### `native_pdf`

- `enabled`: desired native scheduled-report status.
- `owner_user_id`: Zabbix report owner/user ID.
- `dashboard_id`, `dashboard_name`: dedicated report dashboard identity.
- `web_service_url`: must end in `/report`.
- `report_writers`: bounded Zabbix server writer count (normally `1`).
- `recipient_user_ids`, `recipient_group_ids`: Zabbix API IDs, never inferred from email text.

`config/dashboard-blueprint.json` documents the concise dashboard sections. Create/validate the dedicated dashboard in Zabbix, then place its ID in configuration. The custom HTML report already includes current availability, site availability, current down devices, previous-day downtime/new/resolved events, High/Disaster problems, flapping, freshness, HA, utilization, and optional CPU/memory exceptions.

## Credentials and timer

Populate `/etc/zabbix-daily-reporting/secrets.env` without quotes or shell code:

```text
ZABBIX_API_TOKEN=
ZABBIX_API_USER=
ZABBIX_API_PASSWORD=
DAILY_REPORT_SMTP_PASSWORD=
```

Prefer a dedicated least-privilege API token with read access to the in-scope hosts/problems/items. Then enable the timer:

```bash
sudo ./scripts/install_daily_reporting.sh --enable-timer
systemctl list-timers zabbix-daily-report.timer
```

Changing the schedule requires updating both `schedule_local` and the timer `OnCalendar`, followed by `systemctl daemon-reload && systemctl restart zabbix-daily-report.timer`.

## Manual custom report test

```bash
sudo systemctl start zabbix-daily-report.service
sudo journalctl -u zabbix-daily-report.service -n 50 --no-pager
```

The service reads the protected environment file without putting secret values on the command line.

## Native Scheduled PDF setup

Zabbix 7.0 native reports require the matching `zabbix-web-service`, a supported Chrome/Chromium executable, `WebServiceURL` ending in `/report`, nonzero `StartReportWriters`, a reachable Frontend URL, and recipient Zabbix users with enabled email media. See the official [web service installation](https://www.zabbix.com/documentation/7.0/en/manual/appendix/install/web_service), [web service configuration](https://www.zabbix.com/documentation/7.0/en/manual/appendix/config/zabbix_web_service), [scheduled reports](https://www.zabbix.com/documentation/7.0/en/manual/config/reports), and [email media](https://www.zabbix.com/documentation/7.0/en/manual/config/notifications/media/email) documentation.

Detect without changing anything:

```bash
sudo /usr/bin/python3 /opt/zabbix-daily-reporting/bin/native_preflight.py --json
```

Missing RPMs are prerequisites; this project does not download them or assume Internet-enabled DNF. After they are supplied through the approved RHEL/Zabbix offline repository process, review the proposal:

```bash
sudo ./scripts/install_daily_reporting.sh --preflight
sudo bash -c 'set -a; . /etc/zabbix-daily-reporting/secrets.env; set +a; exec sudo -E -u zabbix-report /usr/bin/python3 /opt/zabbix-daily-reporting/bin/native_reporting.py --config /etc/zabbix-daily-reporting/report.json'
```

Only after review:

```bash
sudo ./scripts/install_daily_reporting.sh --apply-native-config
sudo bash -c 'set -a; . /etc/zabbix-daily-reporting/secrets.env; set +a; exec sudo -E -u zabbix-report /usr/bin/python3 /opt/zabbix-daily-reporting/bin/native_reporting.py --config /etc/zabbix-daily-reporting/report.json --apply'
```

The installer writes only `/etc/zabbix/zabbix_server.conf.d/daily-reporting.conf`, validates with `zabbix_server -T`, retains backups, and refuses the change if prerequisites or the include convention are absent. The API helper validates dashboard visibility before changing the Frontend URL or scheduled report.

## Sites, recipients, and thresholds

- Add/remove sites in `scope.sites`; leave empty for all monitored hosts.
- Change custom recipients in `delivery.recipients`.
- Change native recipients using explicit Zabbix user/group IDs.
- Change thresholds in `thresholds`. Raw CPU/memory threshold evaluation remains opt-in to avoid inventing severity where templates have no validated trigger.

Validate JSON after every change:

```bash
python3 -m json.tool /etc/zabbix-daily-reporting/report.json >/dev/null
sudo ./scripts/verify_daily_reporting.sh
```

## Rollback

```bash
sudo ./scripts/rollback_daily_reporting.sh --confirm
```

Rollback disables the timer, restores the most recent application/native drop-in backup where present, and preserves operator configuration, secrets, and generated reports.

## Troubleshooting

- `certificate verify failed`: install the issuing CA in the RHEL trust store and set `ca_file`; never disable TLS verification.
- `API credentials are absent`: populate the protected secrets file; do not commit credentials.
- `configured native dashboard ID is not visible`: grant the report owner access or correct the ID.
- `NATIVE_PDF=NOT_READY`: run `native_preflight.py --json` and satisfy only the listed offline prerequisites.
- No email: verify Zabbix email media for native PDFs or SMTP settings for custom HTML; test relay policy from the server.
- Empty sections: confirm host group/site filters and API principal permissions.

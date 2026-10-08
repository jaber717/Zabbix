# KPI and worksheet definitions

All reports use the same building blocks. Period boundaries are half-open `[start, end)` in `report.timezone` (default `Asia/Riyadh`); the weekly period is the ISO week
(Monday–Sunday; `suite.json` `week_start: "sunday"` is supported); the monthly period is the calendar month. A scheduled run reports the **last complete period**.
`N/A` (JSON `null`, empty XLSX cell) means "no data" and is never `0`.

## Building blocks

| Term | Definition |
|---|---|
| Incident | One Zabbix problem event, de-duplicated by event id. Overlap rule: it counts if it started before the period end and had not recovered before the period start. A multi-host event is **one** incident in fleet counts and appears against every host in per-host tables. |
| Started / resolved in period | `start ∈ [period)` / `recovery ∈ [period)`. |
| Open at period end | Not recovered, recovered at/after the period end, or marked recovered with an unreadable recovery time (flagged in the warnings). |
| Duration in period | `min(end, period end) − max(start, period start)`; open incidents run to the period end. The full duration (not clipped) is used for MTTR. |
| Downtime class | Incident whose name contains one of `classification.downtime_problem_patterns` (RC2 setting, case-insensitive). |
| Downtime (per device) | Union of the downtime-class incident intervals attributed to the device, clipped to the period; overlaps are merged, never double-counted. |
| MTTR | Mean of (recovery − start) over incidents resolved in the period. N/A when none. |
| Availability (per device) | `icmp` basis: ICMP-ping samples with value 1 ÷ all ICMP samples (history for daily, hourly trend means weighted by sample count for weekly/monthly), used when sample coverage ≥ `sla.min_coverage` (0.90). Otherwise `events` basis: `100 × (1 − downtime ÷ period seconds)` with confidence LOW. N/A if the device has no ICMP item and an unknown current state. Site/fleet value = mean over devices that have a value. |
| Coverage | Samples present ÷ samples expected from the item update interval (N/A if the interval is a macro/flexible). |
| Confidence | HIGH ≥ 95 %, MEDIUM ≥ 80 %, LOW > 0, NONE no samples, UNKNOWN coverage not derivable. A site/fleet confidence is the **worst** of its devices. |
| Flapping | Device with ≥ `thresholds.flapping_events` downtime-class incidents that **started** in the period. |
| Stale | Newest ICMP item value older than `thresholds.stale_data_minutes` at generation time. Devices without an ICMP item are not evaluated. |
| Interface utilization | rate ÷ capacity. Capacity = configured `capacity_bps`, else the maximum of the `net.if.speed` item in the period; none → utilization **N/A** (the rate is still reported). |
| P95 (hourly avg) | Nearest-rank 95th percentile of the hourly trend averages. It is **not** a 5-minute percentile and understates short peaks. A raw `P95` exists only where raw history is read. |
| Peak (hourly) | Maximum of the hourly trend maxima. |

## 1. Daily Network Health — daily — `daily-network-health`

| KPI | Definition |
|---|---|
| Devices monitored / Available now / Down now / State unknown | Current `available` state of the host interfaces (RC2 semantics): DOWN if any interface is unavailable, UP if any available, else UNKNOWN. |
| Availability (fleet) | See *Availability*. Note shows "N of M devices have a value". |
| Incidents started / resolved | In the period (see Incident). |
| Open High/Disaster now | Currently open problems with severity High or Disaster (`problem.get`, any age). |
| Flapping devices, Stale devices | See definitions. |

Worksheets: **Summary**, *Availability by site*, *Open High / Disaster problems (now)*, *Incidents in period*, *Devices* (basis, coverage, confidence, downtime, flags), **Charts**, **Data Dictionary**, **Audit**.

## 2. WAN & ISP Performance — weekly — `wan-isp-performance`

Links must be declared in `suite.json` → `wan.links` (host, interface name as in the `interface` item tag, ISP, optional site, optional `capacity_bps`).

| KPI | Definition |
|---|---|
| WAN links in report / ISPs | Declared links that resolved to a host in scope. |
| Mean link availability | Mean of per-link `ifOperStatus` history (value 1 = up) ratios; weekly raw history is used because a status trend average is not an up ratio. |
| Highest peak utilization / Links at/above threshold | Per link `max(in peak, out peak) ÷ capacity` vs `thresholds.interface_utilization_percent`. |
| Links without capacity / Declared links not found | Data gaps, listed in *Exceptions*; never guessed. |

Worksheets: *ISP comparison*, *Daily peak and average rate* (per local day, sum over links), *WAN links* (capacity and source, in/out average, peak, P95 hourly, utilization, availability, status coverage, error/discard averages, RTT/loss of the link host, confidence), *Exceptions*, *WAN-device incidents*.
Error/discard columns are averages of the item values (item units, not totals).

## 3. Infrastructure Health — weekly — `infrastructure-health`

| KPI | Definition |
|---|---|
| Devices assessed | Devices in scope (optionally limited by `infra.host_groups`). |
| Fleet CPU / memory average | Mean of device averages (hourly trends). |
| Devices with hours over threshold | Device with ≥ 1 hour whose average ≥ `cpu_percent`/`memory_percent`, or an hourly max above it. |
| Devices without CPU/memory data | Listed as N/A, not healthy. |
| Devices with a reboot | Uptime counter dropped between consecutive hours (`min < previous max − 60 s`). |

Worksheets: *Top CPU*, *Top memory* (P95 of hourly averages), *Threshold exceptions*, *Device resource summary* (avg, hourly max, P95 hourly, hours over, coverage, reboots, incidents).

## 4. Executive Summary — monthly — `executive-summary`

| KPI | Definition |
|---|---|
| Availability (fleet) and Change vs previous month | Same method on this and the preceding calendar month; change in percentage points. |
| Availability vs SLA target | Availability shown against `sla.target_percent`, **only** if at least half of the devices have HIGH/MEDIUM confidence; otherwise N/A with a finding that says why. |
| Incidents / High-Disaster / Open at month end | Incident counts with the previous month in the note. |
| Mean time to resolve | MTTR. |
| Total device downtime | Sum of per-device merged downtime from downtime-class **events** (a device that is down by ICMP but has no problem event contributes availability loss but no event downtime). |
| Highest WAN peak utilization | From declared links (trend based); N/A without links or capacity. |

Worksheets: *Site scorecard* (this vs previous month, meets target), *Incidents by severity*, *Devices with most downtime*, *WAN utilization (peaks)*.

## 5. Incident Analysis — weekly — `incident-analysis`

KPIs: incidents in period, started, resolved, open at period end, High/Disaster, MTTR, acknowledged %, downtime-class impact (sum over incidents, not merged across devices).
Worksheets: *By severity*, *By site*, *Incidents started per day* (every local day listed), *Most affected devices*, *Recurring problems (2 or more)*, *Longest incidents (in period)*, *Incident log*.

## 6. Monitoring Quality — weekly — `monitoring-quality`

| KPI | Definition |
|---|---|
| Devices with data issues | Device state not UP, interface error, no/stale ICMP item, no site, unsupported items, no CPU or memory item. |
| Devices with HIGH confidence | Minimum of ICMP/CPU/memory sample coverage ≥ 95 %. |
| Unsupported items | `item.get` with `state = 1` on monitored items. |
| API truncations / Failed API requests | What the collector could not read completely, from the audit trail. |
| Declared WAN links not found | See report 2. |

Worksheets: *Collector diagnostics*, *Device data quality*, *Unsupported items*.

## Common XLSX features

Summary sheet (period, timezone, generated, source, dataset hash, KPIs with display text and definition id, findings, warnings), one worksheet per table as a filterable Excel table with a frozen header row,
typed numbers/dates and number formats (`#,##0`, `0.00"%"`, `yyyy-mm-dd hh:mm`), conditional formatting on thresholds and statuses, native Excel charts on a **Charts** sheet, **Data Dictionary**, **Audit**
(dataset SHA-256, generation time, period, API calls per method, truncations, failures, scope and limits). No formulas (strings beginning with `= + - @` are stored as text) and no macros.

# Interface alerting as code (Zabbix 7.0)

List the interfaces that must alert in **one YAML file**. Three commands validate, preview and apply it.
Everything else stays monitored exactly as before.

```bash
vi config/interfaces.yaml        # 1. edit
./apply.sh --check               # 2. PASS / FAIL for every interface, nothing changes
./apply.sh --dry-run             # 3. shows what would be ADDed / CHANGEd / REMOVEd
./apply.sh                       # 4. applies it; run again and it says "No changes required."
```

Setup once: `cp .env.example .env` and fill in `ZABBIX_URL_LAB` / `ZABBIX_TOKEN_LAB` (an API token).
Needs `python3` and PyYAML (`apt install python3-yaml`). `.env` is git-ignored.

## The file

```yaml
defaults:                         # applies to every interface below unless overridden
  severity: high                  # warning | average | high | disaster
  utilization: {enabled: false, threshold: 70, recovery: 65, poll_interval: 10s}
  errors:   {enabled: true, rate: 1}      # per second
  discards: {enabled: true, rate: 1}
  flapping: {enabled: true, transitions: 3, window: 10m}

hosts:
  RTR-01:                         # exact Zabbix host name
    site: HQ
    interfaces:
      HundredGigE0/0/0/0:         # exact interface name as Zabbix shows it
        description: STC Internet
        role: ISP
        severity: disaster
        expected_speed: 100G      # optional: alert if it renegotiates lower
        utilization: {enabled: true, threshold: 70, recovery: 65}
```

* **Add an interface**: add a block under its host, run the three commands.
* **Link de-duplication**: give both ends of a link the same `link_id`; set `notify: false` on one end.
* **Remove an interface (or a whole host)**: delete the block. Its alerts and the macros the tool made disappear; the interface itself is still monitored by the stock templates.
* **Change a threshold**: edit the number. `--dry-run` shows `live '80' -> git '70'`.
* A full example is in `examples/interfaces.sample.yaml`; `schemas/interfaces.schema.json` gives editor completion.

## What alerts

| Alert | Fires when | Clears when |
|---|---|---|
| Link DOWN / UP | newest polled `ifOperStatus` is not up(1) — on the very next poll, no delay window | status is up(1) |
| Utilization RX / TX | newest sample > `threshold` % of link speed (`last()`, no average) | newest sample < `recovery` % |
| Error / discard rate | newest rate > `rate` per second | newest rate ≤ `recovery` (default 0) |
| Flapping | ≥ `transitions` status changes in `window` | fewer changes in the window |
| Speed below expected | `expected_speed` set and `ifHighSpeed` is lower | back to expected |

Flapping: the **first** DOWN is always reported on the next poll. If the link then bounces, the Link DOWN problem stays open (it cannot recover while the link is flapping), so you get no stream of DOWN/UP messages, plus **one** Flapping problem. If the link ends up down, the DOWN problem simply stays open — a persistent outage is never hidden. It recovers once the link is up and quiet for `window`. Both ends of one physical link carry the same `link_id`; only one end has `notify: true`, the other still raises tagged problems but the action skips them.

Severity is per interface (`severity:`). Messages carry device, site, interface, description, role, severity, direction, threshold, observed value and capacity (see `netalert/model.py`).

## Environments

`config/environments/<name>.yaml` says which variables hold the URL and token. LAB and PRODUCTION never share them.

```bash
./apply.sh --env production --check
./apply.sh --env production --dry-run
./apply.sh --env production --confirm production      # production writes need the name typed
```

Before anything is read or written the tool proves **which Zabbix it is talking to**: the server must carry a global macro `{$NETOPS.ENVIRONMENT}` equal to `--env`, the API must be 7.0.x, the URL must match the environment's `url_regex`, and the same URL must not be configured for another environment. LAB claims itself on first apply; PRODUCTION is claimed once, deliberately: `./apply.sh --env production --init-identity --confirm production`. A mismatch stops everything.

## Safety rails

* Only objects this tool owns are touched: host macros `{$NETOPS.*}` (marked `managed_by=zabbix-alerting-as-code` in their description) and the template **NETOPS Interface Alerting**. A same-named object without the marker is reported `REVIEW REQUIRED` and left alone.
* If any check fails, nothing is applied. `--check` and `--dry-run` cannot write (the client refuses write methods).
* Before every apply the managed objects are saved to `state/backups/<env>-<time>.json`. Rollback = `git revert` the YAML and apply again.
* An `interfaces.yaml` that selects nothing is refused (it would remove every alert) unless you pass `--allow-empty`.
* No direct database access; only the Zabbix API and `configuration.import`.

## Tests

```bash
python3 -m unittest discover -s tests -t .      # offline, ~1 s
./scripts/lab-write-test.sh                      # real LAB: needs a write-capable token (see below)
```

Offline tests run the real CLI against an in-memory model of the Zabbix 7.0 API. They prove the logic; they do **not** replace a run on a real server. See `docs/DESIGN.md` → *Validation status*.

## Not in this tool

Device configuration, SNMP traps (see `docs/DESIGN.md` for why polling is used), the SMTP/media type (never modified), existing dashboards, hosts and stock templates.

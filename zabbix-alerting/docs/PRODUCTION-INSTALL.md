# Production installation (direct from GitHub)

Runs on the company's Zabbix VM (or any Linux host that can reach the Zabbix API). Needs `git`, `python3` (3.8+) and PyYAML.
**Production has its own inventory and notification settings. Nothing from LAB is reused**: no LAB routers, no Telegram
bot token / chat id, no SNMP credentials. This repository contains none of them.

## 1. First-time setup

```bash
sudo dnf install -y git python3 python3-pyyaml        # or: apt install git python3 python3-yaml
git clone https://github.com/jaber717/Zabbix.git
cd Zabbix && git checkout v1.0.0                      # always deploy a tag, not a moving branch
cd zabbix-alerting
python3 -m unittest discover -s tests -t .            # optional sanity check (offline, ~2 s)
```

### Credentials (kept out of Git)
Create a **dedicated Zabbix API token** for a service user that may: read hosts/items/templates, write host user macros,
link templates, import configuration, create global macros and manage actions (a custom role with those API methods; super admin
works but is broader than needed).

```bash
cp .env.example .env && chmod 600 .env
vi .env          # set ONLY the PRODUCTION pair:
                 #   ZABBIX_URL_PRODUCTION=https://<production zabbix frontend>
                 #   ZABBIX_TOKEN_PRODUCTION=<api token>
```
`.env` is git-ignored. Do not put LAB values in it (leave `ZABBIX_URL_LAB`/`ZABBIX_TOKEN_LAB` empty on this host).

### Tell the tool which server is production
Edit `config/environments/production.yaml`: set `zabbix.url_regex` to a regex that matches only your production URL (it ships as a
placeholder that matches nothing, so the tool refuses to run until you do). Commit this change on your own deployment branch if you track it.

Claim the server once (creates the global macro `{$NETOPS.ENVIRONMENT}=production`; afterwards a run that points at any other
Zabbix is refused):

```bash
./apply.sh --env production --init-identity --confirm production
```

### Notifications (production-owned)
Configure the real notification path **inside Zabbix** first (your own media type, e.g. e-mail or a Telegram bot created for production,
and a user group whose users have that media). This tool never creates or edits media types or users. Then in
`config/environments/production.yaml` uncomment and fill `alert_action:` with the **group name** and the **media type name**. Do not
reuse the temporary LAB Telegram bot: it will be revoked when LAB is decommissioned.

## 2. Add production interfaces
Edit **`config/interfaces.production.yaml`** (shipped empty). Use the exact Zabbix host name and the exact interface name Zabbix shows
(the `interface` tag of the host's items). Give both ends of a link the same `link_id`.

```yaml
hosts:
  RTR-A:
    site: HQ
    interfaces:
      HundredGigE0/0/0/0:
        description: To RTR-B
        role: P2P
        severity: disaster
        link_id: P2P-001
        utilization: {enabled: true, threshold: 70, recovery: 65}
```
`examples/interfaces.sample.yaml` shows every option. Do not copy `config/interfaces.lab.yaml`.

## 3. Check, dry-run, apply

```bash
./apply.sh --env production --check                  # PASS/FAIL per interface; changes nothing
./apply.sh --env production --dry-run                # banner + ADD/CHANGE/REMOVE; changes nothing
./apply.sh --env production --confirm production     # applies; backs up managed objects first
./apply.sh --env production --dry-run                # must print: No changes required.
```
Stop if anything prints `FAIL`, `REVIEW REQUIRED`, `IDENTITY MISMATCH` or **`VERIFICATION INCOMPLETE`**. The last one means the
token cannot read the template definition (`configuration.export` / `triggerprototype.get`), so the result is not trusted and nothing is applied.

## 4. Verify
1. The final line of the apply is `verification plan is empty`, and the second dry-run says `No changes required.`
2. Data → Latest data → host → tag `interface`: `netops.if.oper`, `.in`, `.out`, `.speed` items are supported and updating (10 s / 60 s).
3. `python3 scripts/lab_verify_objects.py --env production --config config/interfaces.production.yaml` (read-only) checks template, links, macros and discovered items.
4. Prove an alert path on one non-critical link in a maintenance window before relying on it.

## 5. Update to a new release
```bash
cd Zabbix && git fetch --tags && git checkout vX.Y.Z && cd zabbix-alerting
./apply.sh --env production --dry-run      # review, then apply with --confirm production
```

## 6. Rollback
Rollback is "return the inventory to the previous Git state and apply again" (idempotent):
```bash
git log --oneline -- config/interfaces.production.yaml      # find the last good commit
git checkout <good-commit> -- config/interfaces.production.yaml
./apply.sh --env production --dry-run                       # shows the REMOVE / CHANGE that undo the mistake
./apply.sh --env production --confirm production
```
To go back to an older framework release, check out the older tag and run the same dry-run/apply. Every apply first writes
`state/backups/production-<time>.json` (owned macros, template export, action, identity) as an audit record of what was there.
To switch the tool off entirely: set `hosts: {}` and run with `--allow-empty` — it removes only what it created.
The rollback path was exercised offline against the Zabbix API model; it has not been exercised on a production Zabbix.

## 7. What the tool will never do
Modify media types, users, stock templates or stock triggers; touch objects it does not own (a same-named object without the
`managed_by=zabbix-alerting-as-code` marker is reported `REVIEW REQUIRED` and left alone); run against a Zabbix whose identity
macro is not `production`; or write to production without `--confirm production`.

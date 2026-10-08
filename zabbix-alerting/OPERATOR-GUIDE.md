# Operator guide - Interface alerting as code

You list the interfaces that must alert in one YAML file. Three commands check, preview and apply it. Run everything from
`Zabbix/zabbix-alerting/`. Add `--env production` for production (and `--confirm production` to apply there).

```bash
./apply.sh --check        # PASS / FAIL per interface. Changes nothing.
./apply.sh --dry-run      # shows ADD / CHANGE / REMOVE. Changes nothing.
./apply.sh                # applies. Run --dry-run again: it must say "No changes required."
```
Inventory files: `config/interfaces.lab.yaml` and `config/interfaces.production.yaml` (each environment reads only its own).

**What this tool does and does not do.** It manages alerting for interfaces of hosts that *already exist in Zabbix* with SNMP
monitoring. It does **not** create hosts, SNMP credentials, media types or users, and it does not configure routers.

## Stop signs
`FAIL`, `REVIEW REQUIRED`, `IDENTITY MISMATCH` and `VERIFICATION INCOMPLETE` all mean: nothing was applied. Fix the cause and re-run.
`VERIFICATION INCOMPLETE` = the API token cannot read the template definition, so the result cannot be trusted.

## Add an interface to an existing host
```yaml
hosts:
  RTR-A:                      # exact Zabbix host name
    interfaces:
      HundredGigE0/0/0/1:     # exact interface name as Zabbix shows it (item tag "interface")
        description: To RTR-B
        role: P2P
        severity: disaster    # warning | average | high | disaster
        link_id: P2P-002      # same value on the other end of the link
        utilization: {enabled: true, threshold: 70, recovery: 65}
```
```bash
./apply.sh --check && ./apply.sh --dry-run && ./apply.sh
```
A typo is refused with a suggestion (`did you mean 'Gi0/1'?`). Discovery of the new items takes up to 5 minutes (the tool also queues it).

## Remove an interface
Delete its block (delete the whole host block to remove a host). Then `--dry-run` shows `REMOVE`, then apply.
The interface stays monitored by the stock templates; only the alerts and macros this tool created disappear.

## Change a utilization threshold
Edit `threshold` and `recovery` (recovery must be lower than threshold). `--dry-run` shows `live '70' -> git '85'`. Apply.
Defaults for all interfaces live under `defaults:` at the top of the file.

## Add a new device and its interfaces
1. **In Zabbix (not this tool):** create the host with an **SNMP interface**, link the stock SNMP interface template that produces
   interface items (for Cisco: "Cisco IOS by SNMP"), set that host's SNMP credential macros. Wait for interface discovery to finish
   (items tagged `interface` appear).
2. `./apply.sh --check` should now list the host's interfaces as present. Before step 1, it says
   `host 'X' not found in Zabbix` or `host has no items tagged interface` - that is expected, nothing was changed.
3. Add the host and its P2P interfaces to the inventory (block above, with the same `link_id` on both ends), then check, dry-run, apply.

## Notifications: Telegram in LAB, e-mail in Production
The action is declared per environment in `config/environments/<env>.yaml`; trigger logic is identical.
```yaml
alert_action:
  name: "NETOPS-IaC Interface Alerts"
  enabled: true
  usergroups: ["Network Operations"]   # Zabbix user group; its users need the media active
  media_type: "Email"                  # LAB currently uses "Telegram"
```
Create the SMTP media type and the users' e-mail addresses in Zabbix first (this tool never edits them). Problem and recovery
messages both go through that media type. To switch media later change only `media_type` and run `--dry-run` (one `CHANGE action`) then apply.

## Production deployment
See `docs/PRODUCTION-INSTALL.md` (clone, first-time setup, credentials, upgrade, rollback). Production has its own inventory,
its own Zabbix token and its own notification settings; nothing from LAB is copied.

## Roll back
```bash
git log --oneline -- config/interfaces.production.yaml
git checkout <good-commit> -- config/interfaces.production.yaml
./apply.sh --env production --dry-run && ./apply.sh --env production --confirm production
```
Backups of what the tool owned are written to `state/backups/` before each apply (audit record).

## Reference
Alerts: link DOWN/UP (next poll, 10 s), RX/TX utilization (newest sample, separate problems, recovery below the recovery value),
errors, discards, flapping (one problem; the first DOWN is never suppressed), speed below `expected_speed`. Both ends of a link
alert and notify; `link_id` ties them together in the event tags. Design and validation status: `docs/DESIGN.md`.

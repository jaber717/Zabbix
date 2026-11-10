# Discovery-assisted onboarding (v1.1.0 candidate)

`./onboard.sh` replaces hand-written inventory YAML. It reads the live Zabbix (read-only), proposes candidate ports
and devices, lets you approve them in a terminal, generates both inventories, audits monitoring coverage, and gates
deployment. The existing `apply.sh` / `apply-health.sh` still do every write, unchanged.

> **Status:** tested offline against an in-memory Zabbix 7.0 model (228 tests, Python 3.9 and 3.13). It has **not**
> run against the LAB or Production Zabbix. See *Remaining production validation gates* at the end.

## 1. What it does, and what it never does

| Step | Zabbix access | Files written |
|---|---|---|
| discovery + coverage audit | read-only client: any write method raises before sending | `state/onboarding/<env>/coverage-*.md` (git-ignored) |
| review (`a`, `x`, `r`, `s`, `d`, `p`, `f`) | none | `config/onboarding.<env>.yaml` after each command |
| write (`w`) | read-only dry-run of both tools | `config/interfaces.<env>.yaml`, `config/network-health.<env>.yaml` (previous copies in `state/onboarding/<env>/backups/`) |
| `--verify` | read-only | none |
| `--deploy --confirm production` | **writes, through the existing `apply.sh` / `apply-health.sh` only** | backups in `state/backups/` |

Never: creating or deleting items/triggers outside the project's own template, editing stock templates, host settings,
actions or media, disabling monitoring, restarting services, touching devices. Network ports are taken from the items the
stock interface templates already discovered (item tag `interface`), not from Zabbix host interfaces.

## 2. Install and update — GitHub only, directly on the RHEL 9 VM

One time (as the service user that will run the tool):

```bash
# only if SSL inspection re-signs github.com / your Zabbix: trust the company root CA system-wide (git and python use it)
sudo cp company-root-ca.pem /etc/pki/ca-trust/source/anchors/ && sudo update-ca-trust
# only if outbound HTTPS needs a proxy
export https_proxy=http://<proxy>:<port>
rpm -q python3-pyyaml || sudo dnf install -y python3-pyyaml      # from your configured RHEL repository

git clone --branch claude/discovery-onboarding-v1.1 https://github.com/jaber717/Zabbix.git ~/Zabbix
cd ~/Zabbix/zabbix-alerting
git checkout -b prod-local && git remote set-url --push origin no-push   # production inventories never leave this VM
./onboard.sh --env production                                             # first run asks for URL + token
```

The first run asks for the Zabbix URL, API token (hidden) and an optional NetBox URL/token, stores them in `.env`
(mode 600, git-ignored) and offers to set the production URL guard (`url_regex`). Re-enter them with `--setup`.
API token: a dedicated service user. Discovery needs read access to hosts, items, triggers, actions and media types;
reading users and user groups is optional (without it notification coverage is reported as UNVERIFIED). The one-time
`./apply.sh --env production --init-identity --confirm production` and deployment need a Super admin service user.

Update:
```bash
cd ~/Zabbix && git fetch origin && git merge origin/claude/discovery-onboarding-v1.1   # your config commits are kept
```
If a merge ever conflicts in `config/*.production.yaml`, keep **your** version (`git checkout --ours <file>`).

## 3. Walkthrough: from an existing Zabbix to validated inventories

```bash
./onboard.sh --env production                      # 1. discover + audit + review session
```
```
COVERAGE  PROTECTED / VERIFIED 0 | PARTIALLY COVERED 1 | NOT COVERED 4 | STALE / UNKNOWN 1 | REVIEW REQUIRED 0
  #  S HOST                 PORT          OPER  SPEED ROLE  SEVERITY DESCRIPTION / NOTE
  1  P CORE-SW-01           Eth1/1        up    1G    DCI?  high     DCI to DC2 core  [description matches DCI pattern]
  2  P EDGE-RTR-01          Hu0/0/0/0     up    10G   ISP?  high     STC INTERNET TRANSIT 10G
  3  P EDGE-RTR-01          Te0/0/0/1     up    1G    P2P?  high     P2P TO EDGE-RTR-02 ...  [suggested peer: EDGE-RTR-02|Te0/0/0/1]
  ...
onboard> v 3          # evidence: freshness, ifIndex, triggers, notification path, pairing
onboard> a 1-5        # approve the suggested candidates (blocked ones are refused with the reason)
onboard> p 3          # confirm the suggested P2P peer (you checked it) -> shared link_id on both ends
onboard> s disaster 2 # explicit severity change (never automatic)
onboard> h            # devices: Network Health (UNTESTED) - approve/adjust features per device
onboard> w            # write both inventories -> strict validation -> read-only dry-run of both tools
onboard> q
```
```bash
git add config && git commit -m "onboarding: approved production inventory"     # 2. keep the three files together
./onboard.sh --env production --verify                                           # 3. gate (read-only)
./onboard.sh --env production --deploy --confirm production                      # 4. gate again, then apply
./onboard.sh --env production --report                                           # 5. coverage after deployment
```
No YAML is typed. The only free text is an optional description (`d N text`) when a port has no ifAlias.

### Review commands
`l [pending|approved|excluded|review|all] [text]` list · `v N` details · `a N..` approve · `x N..` exclude (or remove an
approved entry on the next write) · `u N..` undo · `r ISP|WAN|DCI|P2P N..` role · `s warning|average|high|disaster N..`
severity · `d N text` description · `p N M` pair / `p N` accept suggested peer / `p N -` unpair · `h` devices view ·
`f N +ospf -cpu` features · `pl N cisco-ios|cisco-nxos|huawei-vrp|host-resources` platform · `c` coverage · `w` write · `q`.
Ranges: `3`, `1,4,7-12`, `all` (all rows of the current listing). Batch: `./onboard.sh --env production --commands file.txt`.

## 4. How suggestions and pairings are made (and what is never assumed)

* **Candidates:** ports whose ifAlias matches a role pattern (ISP / DCI / WAN / P2P) or names another Zabbix host.
  Patterns, provider names, severity policy, thresholds and the exclude pattern (loopback, VLAN, tunnel, mgmt, …) are
  in `config/onboarding-rules.yaml` (optional; defaults in `netalert/onboarding.py`, example in `examples/`).
* **Nothing is approved automatically.** Suggestions are marked `ROLE?` until you approve.
* **Severity:** `high` for every role unless your rules file sets a policy. `disaster` is never chosen automatically.
* **Thresholds:** new entries get the agreed utilization 70 % problem / 65 % recovery; errors, discards and flapping keep
  the project defaults.
* **Pairing:** a `link_id` is generated only from a **NetBox cable** between two ports that both exist in Zabbix, or from
  your explicit confirmation (`p`). A description that names the other host is shown as a *suggested* peer, never used on
  its own. Similar port names are never paired. ISP links get no `link_id`.
* **Refused approvals (blockers):** host missing/disabled/no SNMP interface, port no longer discovered, two item sets with
  the same name, status item never/stale/unsupported/disabled, a name Zabbix cannot use as macro context.
* **Network Health:** reachability + SNMP-stale are suggested for devices with approved ports; CPU/memory only with a
  platform (from the linked stock template, or set with `pl`); OSPF/BGP stay UNVERIFIED unless Zabbix already holds
  working OSPF/BGP items — enabling them is allowed with a warning after you confirm the MIB with `snmpwalk`.
* **Existing entries** in either inventory are kept verbatim (including custom thresholds, `expected_speed`, `link_id`,
  `defaults`). Only entries you change or exclude are touched. Repeated runs produce byte-identical files.

## 5. Coverage audit

`state/onboarding/<env>/coverage-latest.md`, for candidates, approved and project-managed ports plus all devices:

| Class | Meaning |
|---|---|
| PROTECTED / VERIFIED | fresh data, enabled link-state trigger not switched off by its macros, a utilization alert, and a notification path proven READY: enabled action whose conditions match, problem **and** recovery operations, enabled media type, ≥1 recipient with active media for that severity and read permission on the host |
| PARTIALLY COVERED | some alerting exists but one of the above is missing or unprovable |
| NOT COVERED | no enabled link-state trigger |
| STALE / UNKNOWN | host disabled, SNMP unavailable, status item stale/never/unsupported, trigger in UNKNOWN state |
| REVIEW REQUIRED | ambiguous name, port vanished, SNMP index changed, pairing conflict |

It also lists existing alerts that are preserved, pairing status, devices without fresh data, unsupported/unverified
health checks, actions without recovery operations, disabled media, and everything the token could not read.
Template-level tags and time-period action conditions cannot be evaluated offline; they can only *lower* the result.

## 6. Deployment gate (`--verify`, also run by `--deploy`) — fails closed on

identity mismatch or unclaimed server · inventories changed since the last reviewed write (hand edits) · generated
files failing either tool's strict validation · any approved port that is missing, stale, unsupported, ambiguous, or whose
host id / status item / SNMP index changed since approval (reuses `handover.cross_check`) · approved health devices
with unsupported features. Warnings (not blocking): unpaired P2P ports, OSPF/BGP enabled while UNVERIFIED, pending candidates.
An empty interface inventory is never deployed by `--deploy` (removing everything stays a manual `./apply.sh --allow-empty`).

## 7. Rollback and recovery

| Situation | Action |
|---|---|
| Wrong approval, not yet deployed | `x N` / `u N`, then `w` |
| Deployed and must revert | `git log -- config/` → `git checkout <good> -- config/interfaces.production.yaml config/network-health.production.yaml config/onboarding.production.yaml` → `./onboard.sh --env production --deploy --confirm production` (the three files carry matching hashes, so the gate passes without re-review) |
| Lost or corrupt decisions file | delete `config/onboarding.production.yaml`, run `./onboard.sh`, `w`: approved entries come back from the inventories; only exclusions must be redone |
| Previous inventory versions | `state/onboarding/production/backups/` (written before every change) |
| Interrupted deploy | re-run the same `--deploy` (both apply tools are idempotent) |
| What Zabbix held before an apply | `state/backups/production-*.json`, `state/backups/network-health-production-*.json` |
| Remove the project's alerting entirely | `./apply.sh --env production --allow-empty --confirm production` with an empty interface inventory (deliberately manual) |

## 8. Remaining production validation gates (not yet done)

1. Run `./onboard.sh --env production --report` against Production: confirm the discovered hosts/ports are plausible and
   the stock item conventions match (`net.if.status[...]` keys, `interface` tag, ifAlias in the `description` tag or item
   name). This is read-only and the first contact with real data.
2. Same against LAB: approve the 18 Codex-validated P2P ports and confirm the generated file makes `./apply.sh --env lab
   --dry-run` report `No changes required.` against the deployed LAB state.
3. Check that the production token can read users/user groups; otherwise notification coverage stays UNVERIFIED.
4. Network owner review of every approved ISP/WAN/DCI/P2P port and every confirmed pairing.
5. Deploy, then prove one Problem and one Recovery **e-mail** in Production (open item H1 from the v1.0.2 review).
6. `--report` after deployment must show the deployed ports as PROTECTED / VERIFIED.
7. Network Health (v1.0.3) remains UNTESTED: complete `docs/NETWORK-HEALTH.md` §8 in LAB before approving any health
   device in Production. Its template import is also not covered by the offline model.
8. Measure discovery time and API load on the full Production inventory.
9. Rollback drill in LAB (section 7, row 2).

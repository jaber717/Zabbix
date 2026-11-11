# Discovery-assisted onboarding (v1.1.0 candidate, remediated)

`./onboard.sh` replaces hand-written inventory YAML. It reads the live Zabbix (read-only), proposes candidate ports
and devices, lets you approve them in a terminal, generates both inventories, audits monitoring coverage, and gates
deployment. The existing `apply.sh` / `apply-health.sh` still do every write.

> **Status:** offline only — 308 tests on an in-memory Zabbix 7.0 model (Python 3.9 and 3.13); the real-API replay test
> is NOT RUN until LAB recordings exist. Never run against LAB or Production yet. Review findings and their fixes:
> `docs/REMEDIATION-v1.1.md`, `docs/REMEDIATION-v1.1-rc3.md`. Remaining gates: section 8 and `docs/LAB-VALIDATION-v1.1.md`.

## 1. What it does, and what it never does

| Step | Zabbix access | Files written |
|---|---|---|
| discovery + coverage audit | read-only client: any write method raises before sending | `state/onboarding/<env>/coverage-*.md` (git-ignored) |
| review (`a x u r s d p h f pl ev ex`) | none | `config/onboarding.<env>.yaml` after each command |
| write (`w`) | read-only dry-run of both tools | both inventories (previous copies in `state/onboarding/<env>/backups/`); decisions hash bound to them |
| `--verify` | read-only, incl. dry-run of both components | none; prints an APPROVAL TOKEN |
| `--deploy --approve TOKEN --confirm production` | **writes, through `apply.sh` / `apply-health.sh` only** | backups in `state/backups/` |

Never: creating or deleting items/triggers outside the project's own templates, editing stock templates, host settings,
actions or media, disabling monitoring, restarting services, touching routers or firewalls. Ports come from items the stock
interface templates already discovered (item tag `interface`), not from Zabbix host interfaces.

## 2. Install and update — GitHub only, directly on the RHEL 9 VM, pinned to a validated commit

One time, as the service user:
```bash
# FortiProxy SSL inspection re-signs github.com: trust its CA system-wide (git and python both use it). Never disable TLS checks.
sudo cp fortiproxy-ca.pem /etc/pki/ca-trust/source/anchors/ && sudo update-ca-trust
# Proxy for GitHub only. Zabbix and NetBox are internal: keep them OFF the proxy (a proxied API call returns 502/504).
cat >> ~/.bashrc <<'EOF'
export https_proxy=http://<fortiproxy>:<port> HTTPS_PROXY=http://<fortiproxy>:<port>
export no_proxy=localhost,127.0.0.1,<zabbix-fqdn>,<netbox-fqdn> NO_PROXY=$no_proxy
EOF
. ~/.bashrc
rpm -q python3-pyyaml || sudo dnf install -y python3-pyyaml            # from the configured RHEL repository

PIN=<validated commit SHA or tag>                                       # never a moving branch
mkdir -p ~/Zabbix && cd ~/Zabbix && git init -q && git remote add origin https://github.com/jaber717/Zabbix.git
git config user.name "netops-$(hostname -s)" && git config user.email "netops@$(hostname -f)"   # local site commits
git config http.lowSpeedLimit 1000 && git config http.lowSpeedTime 60   # abort stalled transfers instead of hanging
for i in 1 2 3 4 5; do git fetch --depth 1 origin "$PIN" && break; echo "fetch failed (proxy 504?) retry $i"; sleep $((i*20)); done
git checkout -q -b prod-local FETCH_HEAD && git remote set-url --push origin no-push   # nothing ever pushed from here
cd zabbix-alerting && ./onboard.sh --env production --setup
git add config && git commit -q -m "site: production settings"
```
`--setup` asks for the Zabbix URL, API token (hidden), optional NetBox URL/token (stored in `.env`, mode 600,
git-ignored), sets the production URL guard (`url_regex`) and pins production deployment to the checked-out GitHub
commit (`deploy_pin`). A shallow fetch transfers only the pinned tree, which avoids the long transfers that hit
FortiProxy 504 timeouts; the loop retries with back-off.

**Validated code vs. site configuration.** `deploy_pin` is the validated application revision and must be a commit
fetched from GitHub (the shallow-fetch boundary or a remote branch) - `--setup` refuses to pin a commit made on the
VM. Your local commits on top of it may change **only** the site configuration: `config/interfaces.<env>.yaml`,
`config/network-health.<env>.yaml`, `config/onboarding.<env>.yaml`, `config/fault-tests.<env>.yaml`,
`config/environments/*.yaml`, `config/onboarding-rules.yaml`. Every other file (code, scripts, templates, docs) must
be byte-identical to `deploy_pin`, committed or not; `--verify`/`--deploy` fail otherwise.

API token: a dedicated service user. Discovery reads hosts, items, triggers, templates, actions, media types, events;
users and user groups are needed to *prove* notification recipients (otherwise UNVERIFIED). Deployment and the one-time
`./apply.sh --env production --init-identity --confirm production` need a Super admin service user.

Update to a newer validated revision (one command; the site configuration is carried over):
```bash
cd ~/Zabbix/zabbix-alerting && ./onboard.sh --env production --update <new validated commit or tag>
./onboard.sh --env production --verify
```
`--update` fetches the commit (shallow, 5 retries with back-off), resets the local branch to it, carries every
site-configuration file over with a 3-way merge (stops without changing anything on a conflict), sets `deploy_pin`
to the new commit, commits, and re-checks. The previous state stays on branch `site-backup-<commit>`.
(A plain `git merge FETCH_HEAD` does not work with shallow fetches: git refuses to merge unrelated histories.)

## 3. Walkthrough: from an existing Zabbix to a deployed, verified inventory

```bash
./onboard.sh --env production                      # 1. discover + audit + review session
```
```
COVERAGE  PROTECTED (DELIVERY TESTED) 0 | CONFIG VERIFIED (DELIVERY NOT TESTED) 0 | PARTIALLY COVERED 1 | NOT COVERED 4 | ...
  #  S HOST                 PORT          OPER  SPEED ROLE  SEVERITY DESCRIPTION / NOTE
  1  P CORE-SW-01           Eth1/1        up    1G    DCI?  high     DCI to DC2 core  [description matches DCI pattern]
  2  P EDGE-RTR-01          Hu0/0/0/0     up    10G   ISP?  high     STC INTERNET TRANSIT 10G
  3  P EDGE-RTR-01          Te0/0/0/1     up    1G    P2P?  high     P2P TO EDGE-RTR-02 ...  [suggested peer: EDGE-RTR-02|Te0/0/0/1]
onboard> v 3          # evidence: freshness, ifIndex, triggers, notification path, pairing
onboard> a 1-5        # approve (blocked rows are refused with the reason)
onboard> p 3          # you confirm the suggested P2P peer -> one shared link_id on both ends
onboard> p 1 -        # this port has no monitored peer (single-ended): required for any unpaired P2P
onboard> h            # devices: Network Health (UNTESTED, production-blocked until LAB acceptance)
onboard> w            # write -> strict validation + link_id integrity -> read-only dry-run of both tools
onboard> q
```
```bash
git add config && git commit -q -m "onboarding: approved production inventory"   # 2. site config only; code stays at deploy_pin
./onboard.sh --env production --verify             # 3. gate + preflight of both components -> APPROVAL TOKEN abc123...
./onboard.sh --env production --deploy --confirm production --approve abc123...   # 4. refuses if ANYTHING changed
./onboard.sh --env production --report             # 5. CONFIG VERIFIED expected; DELIVERY TESTED only after a fault test
# 6. In a change window: take the port down, wait for the Problem e-mail, bring it up, wait for the Recovery e-mail.
./onboard.sh --env production --record-fault-test 'EDGE-RTR-01|Hu0/0/0/0'   # binds that event pair to this config
git add config && git commit -q -m "fault test EDGE-RTR-01|Hu0/0/0/0"
```
`--record-fault-test` accepts only one Problem event and *its* Recovery event from the last 24 h, both SENT by the
proven action to the same user who is still an eligible recipient. The record carries a fingerprint of the trigger,
its macro values, the action and every recipient's groups and media; the audit reports PROTECTED (DELIVERY TESTED)
only while that fingerprint still matches and the events are still in Zabbix history (90 days). Older sent messages
are reported as *historical delivery evidence* and never as a current fault test.
No YAML is typed. Free text is limited to an optional description (`d N text`), MIB evidence references (`ev`) and
expected neighbor lists (`ex`, or `ex N ospf seen` after the first deploy).

### Review commands
`l [pending|approved|excluded|review|all] [text]` · `v N` · `a N..` approve · `x N..` exclude / remove · `u N..` undo ·
`r ISP|WAN|DCI|P2P N..` · `s warning|average|high|disaster N..` · `d N text` · `p N M` pair · `p N` accept suggested peer ·
`p N -` confirmed single-ended (releases any previous peer) · `h` devices · `f N +ospf -cpu` · `pl N PLATFORM` ·
`ev N ospf|bgp REFERENCE` · `ex N ospf|bgp seen|IP,IP` · `c` coverage · `w` write · `q`.
Ranges: `3`, `1,4,7-12`, `all`. Batch: `--commands file.txt`.

## 4. Suggestions, pairings and what is never assumed

* **Nothing is approved automatically**; suggestions show `ROLE?`. Severity is `high` unless your policy file says
  otherwise; `disaster` is never automatic. New entries get utilization 70 % / 65 %.
* **Pairing is one-to-one and reciprocal.** Sources, strongest first: your decision (`p`), a reciprocal NetBox cable, an
  existing `link_id` shared by exactly two entries on different hosts. Every relationship is recorded in the decisions file
  with its source. A description naming another host is only a *suggested* peer. Re-pairing releases the old partner;
  a `link_id` is kept only while its relationship is unchanged and is never reused for a different connection.
* **Blockers (deployment refused):** pairing not reciprocal; NetBox now shows a different cable; a `link_id` used by more
  than two entries or by two ports of one host (`w` refuses to rewrite it until you decide each end); P2P without a peer
  and not confirmed single-ended; peer not approved.
* **Approval refused:** host missing/disabled/no SNMP, port vanished, duplicate name, status item never/stale/unsupported,
  names Zabbix cannot use as macro context.
* **Network Health:** OSPF/BGP need per-device evidence (`ev`) and an expected list (`ex`) or the gate blocks; Network
  Health is refused in production until `network_health_lab_acceptance` is recorded (docs/NETWORK-HEALTH.md).
* **Existing entries** are preserved verbatim; only what you change or exclude is touched; reruns are byte-identical.

## 5. Coverage audit — never "protected" on existence alone

| Class | Meaning |
|---|---|
| PROTECTED (DELIVERY TESTED) | CONFIG VERIFIED **and** a fault test recorded with `--record-fault-test`: one Problem event and *its* Recovery event, both SENT by that action to the same current recipient, with the configuration fingerprint (trigger, macro values, action, recipients, media) unchanged since |
| CONFIG VERIFIED (DELIVERY NOT TESTED) | an enabled link-down trigger and RX **and** TX utilization triggers implementing the approved policy (70 % / 65 % hysteresis; only the NETOPS template shape is accepted) whose **expressions** pass a conservative validator (plain `and` of recognised conditions; gates resolved host → templates → global and open; constants evaluated; recovery possible); **every item those triggers use** readable, enabled, supported and fresh (dependent items by their master); an enabled action whose conditions provably match (full tags incl. template tags, nested host groups, template inheritance); an immediate problem operation **and** a recovery operation, each with ≥1 eligible recipient (active media, enabled media type, severity included, unrestricted active period, enabled user group, read permission — a deny anywhere wins); host not in maintenance. Older sent messages appear as *historical delivery evidence* |
| PARTIALLY COVERED | some alerting exists but a link above is missing or cannot be proven |
| NOT COVERED | no enabled, ungated link-down trigger (disabled or gated-off triggers count as none) |
| STALE / UNKNOWN | host disabled, SNMP unavailable, status item stale/never/unsupported, an item of the link-down trigger stale/disabled/unsupported/unreadable, trigger UNKNOWN |
| REVIEW REQUIRED | ambiguous name, port vanished, ifIndex changed, pairing/link_id issue |

Unknowable inputs (unreadable users/templates/history, custom formulas with unknown inputs, time-period conditions,
regex macro contexts, unrecognised expressions) lower the class; they never raise it.

## 6. Deployment gate (`--verify`; repeated by `--deploy`)

Fails closed on: identity mismatch / unclaimed server · inventory file changed since the reviewed write · **decisions changed
after the last write** · either inventory differing from what the current decisions + live evidence regenerate · invalid
generated files · any `link_id` integrity problem · any approved port missing, stale, unsupported, ambiguous, without
recorded identity evidence, or with host id / status item / ifIndex drift (`handover.cross_check`) · pairing issues ·
unsupported or UNVERIFIED health features, OSPF/BGP without expected lists, Network Health without production acceptance ·
production checkout differing from `deploy_pin` outside the site configuration, or `deploy_pin` not a GitHub commit · **either component's read-only preflight dry-run** failing.
Only pending (unreviewed) candidates are warnings: they are not part of the deployment.

`--deploy` needs the APPROVAL TOKEN from `--verify`. The token covers code commit, decisions, both inventories and both
live plans, so a deploy can only apply exactly what was reviewed. An empty interface inventory is never deployed.

## 7. Rollback and recovery (no automatic multi-component rollback)

| Situation | Action |
|---|---|
| Wrong approval, not yet deployed | `x N` / `u N`, then `w` |
| Deployed and must revert | `git checkout <good> -- config/interfaces.production.yaml config/network-health.production.yaml config/onboarding.production.yaml` → `--verify` → `--deploy --approve <token>` |
| **Partial apply** (Interface Alerting applied, Network Health failed) | printed as `PARTIAL APPLY: completed = ...`. Fix the cause and re-run `--verify` + `--deploy` (both tools are idempotent), or revert as above |
| Interrupted deploy | re-run `--verify` + `--deploy` |
| Lost decisions file | delete it, run `./onboard.sh`, re-confirm exclusions/pairings, `w` |
| Previous inventory versions / prior Zabbix state | `state/onboarding/production/backups/`; `state/backups/*.json` |
| Remove the project's alerting entirely | manual: `./apply.sh --env production --allow-empty --confirm production` |

## 8. Remaining validation gates (not yet done)

Step-by-step, read-only first: `docs/LAB-VALIDATION-v1.1.md`.

1. LAB: `scripts/capture-api-fixtures.py --env lab` (written outside the repository; the script refuses a path inside
   it and refuses to write if any original string survives sanitizing), then
   `NETALERT_RECORDED_DIR=<dir> python3 -m unittest tests.test_recorded_fixtures` must pass (real `selectHostGroups`,
   `selectHostGroupRights`, user media, raw trigger expressions + `selectFunctions`, item tags, event `r_eventid` and
   alert `userid`/`p_eventid`, permission errors). A capture is committed only after an independent confidentiality
   review — never automatically.
2. LAB: onboarding of the 18 accepted P2P ports must regenerate `config/interfaces.lab.yaml` with `No changes required.`.
3. LAB: one Problem + Recovery **e-mail** fault test on a deployed port → `--record-fault-test` → `--report` shows
   PROTECTED (DELIVERY TESTED); then change the action or a recipient's media and confirm it drops to CONFIG VERIFIED.
4. Production `--report` (read-only) reviewed by the network owner; token can read users/user groups.
5. Production deploy pinned to the validated commit, then one e-mail fault test in Production.
6. Network Health: full LAB acceptance (docs/NETWORK-HEALTH.md §8) before `network_health_lab_acceptance` is set.
7. Discovery duration/API load on the full production scope; LAB rollback drill (section 7, row 2).

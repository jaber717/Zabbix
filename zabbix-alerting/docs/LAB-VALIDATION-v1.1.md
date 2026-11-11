# LAB validation procedure — v1.1.0 candidate (read-only first)

**Purpose.** Offline tests have already hidden two API-contract defects (rc3 review: `selectFunctions` field
`name` vs `function`, deprecated `select_alerts`). From here on, only a real Zabbix 7.0 LAB decides. This procedure
is **read-only** until Phase 4, which needs a separate, explicit approval. Production stays untouched; Network
Health production stays blocked; nothing is merged, tagged or released.

Everything runs on the LAB RHEL 9 VM, installed from GitHub only. No SCP, no USB, no workstation installers.

## Phase 0 — prerequisites (one time)

* LAB Zabbix 7.0.x, claimed as `lab` (`{$NETOPS.ENVIRONMENT}` = `lab`). Discovery and the probe stop if it isn't.
* API token of a dedicated service user. The client refuses every write method before sending, whatever the role.
  `user.get` only returns users the token may see; recipient proof (CONFIG VERIFIED) needs to see the NOC users.
* At least one interface with stock SNMP interface items (tag `interface`), one trigger action with e-mail, and,
  for C6, at least one Problem + Recovery e-mail already in the last 30 days (otherwise C6 stays INFO until Phase 4).

## Phase 1 — install the candidate commit (GitHub only)

```bash
PIN=<candidate commit SHA from RELEASE-v1.1.0.md>        # never a branch name
mkdir -p ~/Zabbix && cd ~/Zabbix && git init -q && git remote add origin https://github.com/jaber717/Zabbix.git
git config user.name "netops-$(hostname -s)" && git config user.email "netops@$(hostname -f)"
git config http.lowSpeedLimit 1000 && git config http.lowSpeedTime 60
for i in 1 2 3 4 5; do git fetch --depth 1 origin "$PIN" && break; echo "retry $i"; sleep $((i*20)); done
git checkout -q -b lab-local FETCH_HEAD && git remote set-url --push origin no-push
cd zabbix-alerting && ./onboard.sh --env lab --setup     # URL + token -> .env (mode 600, git-ignored)
```
Record: `git rev-parse HEAD` (must equal `$PIN`), `python3 --version`, `rpm -q python3-pyyaml`, Zabbix version.

## Phase 2 — API contract probe (read-only, prints no names)

```bash
./scripts/lab-contract-probe.py --env lab | tee ~/lab-evidence/probe-$(date +%F).txt
```

| Check | What it settles | Pass condition |
|---|---|---|
| C1 | server version | `7.0.x` |
| C2 | `trigger.get selectFunctions` | function keys exactly `function, functionid, itemid, parameter`; `parameter` starts with `$` |
| C3 / C3b | raw expressions; what `expandExpression` does to user macros | raw form uses `{functionid}` (C3b is INFO) |
| C4 | `event.get selectAlerts` | every event has `alerts`; fields `alertid actionid eventid p_eventid userid mediatypeid status alerttype clock` |
| C5 | problem events | `r_eventid` present |
| C6 | which event a recovery message hangs on | recovery or problem event, never anything else (INFO when no recovery e-mail in the window) |
| C7 | `host.get selectInterfaces` | `available`, `error` present |
| C8 | `usergroup.get selectHostGroupRights` | `id`, `permission`; `users_status` |
| C9 | `action.get` operations | `opmessage` is an object |
| C10 | `user.get selectMedias` | `mediatypeid active severity period` |
| C11 | stock interface items | `net.if.status` items carry tag `interface` |
| C12 | dependent items | `master_itemid` set |

**Stop on any FAIL.** A FAIL is a contract defect: report it with the probe output. Do not work around it in LAB.

## Phase 3 — read-only discovery, audit and capture

```bash
./onboard.sh --env lab --report                          # must print "... API reads, 0 writes"
./scripts/capture-api-fixtures.py --env lab               # -> ~/zabbix-captures/, refused inside the repo
NETALERT_RECORDED_DIR=~/zabbix-captures python3 -m unittest tests.test_recorded_fixtures -v
```
Pass conditions:
1. `--report` completes; coverage classes look plausible to the network owner (spot-check 5 ports with `v N`):
   ports covered only by stock triggers show PARTIALLY COVERED (the stock 90% bandwidth trigger is not the 70/65
   policy) - expected; any port reported CONFIG VERIFIED must really have link + RX/TX policy alerts and recipients.
2. No `{UNKNOWN}` expressions and no "expression logic not recognised" on stock link-down triggers. If you see
   either, the stock template's shape differs from the model: record it, don't approve.
3. The capture's leak check passes, and the replay test passes on it (it is **not** skipped).
4. The 18 accepted P2P ports: `./onboard.sh --env lab` → review → `w` regenerates `config/interfaces.lab.yaml`
   with `./apply.sh --env lab --dry-run` printing `No changes required.` (the file write is local; Zabbix is read).

Evidence to keep: probe output, `state/onboarding/lab/coverage-latest.md`, test output. The capture stays outside the
repository; committing it requires an independent confidentiality review.

## Phase 4 — controlled Problem/Recovery e-mail test (separate approval; writes to LAB only)

Only after Phases 1–3 pass, in an agreed window, on one LAB port the project manages:
1. `./onboard.sh --env lab --verify` → `--deploy --approve <token>` (LAB writes through `apply.sh` only).
2. `--report`: the port is CONFIG VERIFIED.
3. Shut the port; wait for the Problem e-mail; no-shut; wait for the Recovery e-mail. Note both timestamps.
4. `./scripts/lab-contract-probe.py --env lab` → C6 is now PASS (not INFO).
5. `./onboard.sh --env lab --record-fault-test 'HOST|PORT'` → `--report` shows PROTECTED (DELIVERY TESTED).
6. Change one recipient's media severity in LAB → `--report` drops it to CONFIG VERIFIED; revert → PROTECTED.

## Exit criteria

GO for a production read-only `--report` requires: Phase 2 all PASS, Phase 3 conditions 1–4, Phase 4 steps 1–6,
with the evidence above. Network Health (OSPF/BGP) needs its own LAB acceptance (`docs/NETWORK-HEALTH.md` §8) and
stays production-blocked until `network_health_lab_acceptance` is recorded. Until then: **NO-GO**.

# Follow-up remediation — v1.1.0-rc3 (review of rc2 `31ffc94`)

**Status: CANDIDATE, NO-GO for production.** Not merged, not tagged, no GitHub Release, not deployed. Tag `v1.0.2`
is unchanged and remains the only accepted release. Network Health production writes stay blocked
(`network_health_lab_acceptance` absent). Everything below is offline evidence: an in-memory Zabbix 7.0 model and
real temporary git repositories — not a real Zabbix server, not a real e-mail.

## Verdict per finding

| # | Finding | Verdict on `31ffc94` | Fixed in rc3 |
|---|---|---|---|
| 1 | P0 managed item freshness | **Verified code defect** | yes |
| 2 | P0 expanded expressions / gate bypass; utilization policy | **Verified code defect** (both parts) | yes |
| 3 | P1 `deploy_pin` vs local config commits | **Verified code + documentation defect** (plus a second one: the documented update cannot work) | yes |
| 4 | P1 delivery evidence correlation | **Verified code defect** | yes |
| 5 | P1 recorder leaks; NetBox pagination loop | **Verified code defects** | yes |

Whether Zabbix 7.0 *actually* substitutes user macros when `expandExpression` is set (finding 2) is a LAB question;
rc3 no longer depends on the answer (it never asks Zabbix to expand).

## 1. P0 — false green from managed item freshness

*Defect (31ffc94):* `discovery.py:149` stored NETOPS items as bare ids (`p["own"][key] = itemid`);
`coverage.py:360` judged freshness only from the **stock** status item. Reproduced: stock status fresh, NETOPS
`netops.if.oper`/`in`/`out`/`speed` stale, disabled, unsupported or never polled → **CONFIG VERIFIED** in every case.

*Fix:* every item a trigger references is read with its state (`discovery.py:343 _remember`,
`:352 _fetch_missing_items` for items outside the interface tag and for masters of dependent items,
`:371 _quality` judges a dependent item by its master's interval). `coverage.py:370 _quality_problems`: a candidate
link or utilization trigger counts only if **all** of its items are readable, enabled, supported and fresh; otherwise
the port is STALE / UNKNOWN (link) or PARTIALLY COVERED (utilization). A fault-test record does not survive stale data.

## 2. P0 — expression semantics

*Defect (31ffc94):* `discovery.py:210` requested `expandExpression: True`; `coverage.py:69 gates()` only looked for
literal `{$M}=N`; `:89/:97` accepted any expression *containing* a status comparison / any `>` on traffic.
Reproduced: `last(/EDGE-RTR-01/net.if.status[ifOperStatus.1])=2 and 0=1`, top-level `or`/`not`, unknown extra
conditions, a recovery that can never happen, the stock 90 % bandwidth trigger, NETOPS at 90 % or recovery 68 %, RX
without TX, `last(in)>0` — all **CONFIG VERIFIED**.

*Fix:*
* Raw expressions only: `trigger.get` with `selectFunctions`, no `expandExpression` (`discovery.py:213`); rebuilt
  locally (`:386 rebuild`), an unknown function/item reference becomes `{UNKNOWN}` and fails closed. User macros
  stay literal and are resolved by our own resolver (host → template ancestry → global; regex contexts unknown).
* Conservative validator `netalert/exprcheck.py`: an expression must be a plain conjunction (`:81 conjuncts`; any
  top-level `or`/`not` = unknown); every conjunct must be recognised — gate or numeric constant (`:103`, evaluated:
  `0=1` closes the trigger), the test itself, or a known companion (stock change detection, NETOPS speed guard).
  Anything else makes the trigger UNPROVEN. The recovery expression must be able to become true and test link-up
  (`:201 assess_link`); recovery mode "none" does not count.
* Utilization (`:231 assess_util`): only `last(TRAFFIC)*100 > {$NETOPS.UTIL.MAX}*last(SPEED)` with the resolved
  threshold equal to the approved policy (inventory entry, else 70) **and** recovery
  `last(TRAFFIC)*100 < {$NETOPS.UTIL.RECOVER}*last(SPEED)` equal to the approved recovery (else 65); RX **and** TX are
  both required (`coverage.py:422 port_coverage`). The stock bandwidth trigger is reported as "not the approved
  70%/65% policy" — consequence: ports protected only by stock triggers are PARTIALLY COVERED until the NETOPS template
  is deployed on them (intended; the stock template recovers at MAX−3 and defaults to 90 %).

## 3. P1 — validated code vs. site configuration

*Defect (31ffc94):* `onboard_cli.py:139` required `HEAD == deploy_pin`, while `ONBOARDING.md:83` told the operator to
commit the inventories (new HEAD) → every documented production deploy was refused. Conversely `--setup`
(`onboard_cli.py:101`) offered to pin *whatever* was checked out, so `git_code_check(dir, "HEAD")` on a local commit
returned no problem — a local commit could be blessed as validated. Additionally found: the documented update
(`ONBOARDING.md:59`, `git merge FETCH_HEAD` after a shallow fetch) fails with *refusing to merge unrelated histories*.

*Fix (`onboard_cli.py`):*
* `:130 SITE_CONFIG` — the only files a site may commit: inventories, decisions, fault tests, environment files,
  onboarding rules.
* `:156 git_code_check` — `deploy_pin` must be **published** (`:139`: the shallow-fetch boundary in `.git/shallow` or
  contained in a remote-tracking branch; a VM-local commit is neither); HEAD must descend from it; `git diff pin HEAD`
  and the working tree (incl. untracked files) may differ **only** in `SITE_CONFIG`. Code integrity is unchanged:
  any code/script/doc difference, committed or not, fails the gate.
* `--setup` pins only a published commit (`:109` "deploy_pin not offered" otherwise).
* `:207 update_checkout` / `./onboard.sh --update PIN` — the GitHub-only update in one command: shallow fetch with
  retries, branch reset to the new commit, site files carried over by a per-file 3-way merge (any conflict: stop,
  nothing changed), re-pin, commit, re-check; previous state kept on `site-backup-<commit>`.
* `docs/ONBOARDING.md` §2/§3 rewritten; the test asserts the install lines verbatim against the document.

## 4. P1 — delivery evidence

*Defect (31ffc94):* `discovery.py:315` collapsed history to `{trigger: {action: {"problem","recovery"}}}`;
`coverage.py:331 delivered()` → PROTECTED if *any* sent problem and *any* sent recovery existed in 90 days, from
unrelated events, to users who are no longer recipients, regardless of configuration changes since.

*Fix:* raw events with `r_eventid` and alerts with `p_eventid`/`userid`/`mediatypeid` (`discovery.py:315`).
`coverage.py:316 correlated_pairs` accepts only Problem event P + **its** recovery event (alert `p_eventid` = P,
and `P.r_eventid` when reported), both SENT by the proven action to the **same user who is still an eligible
recipient**. PROTECTED (DELIVERY TESTED) now requires an explicit record made after a fault test
(`./onboard.sh --record-fault-test HOST|PORT`, `onboard_cli.py:311`; pair must be < 24 h old) carrying a
configuration fingerprint (`coverage.py:345`: trigger expression/recovery/priority, resolved macro values, action
conditions and operations, recipients' groups/rights/media, media types). Any change → back to CONFIG VERIFIED
("repeat the fault test"); events expired from history → CONFIG VERIFIED. Everything else is reported as
*historical delivery evidence*, never as a current test.

## 5. P1 — recorder and NetBox

*Defect (31ffc94):* `apirecord.py:59 sanitize()` used a deny-list; reproduced leaks (same capture, 31ffc94 sanitizer)
of the interface DNS name, action name, media type name, a non-secret macro value, a host tag value, the trigger
name and the trigger error text (user names and host-group names were already hidden). `netbox.py:75` followed a repeated same-origin `next`
URL without limit (reproduced: 51 requests until the test opener stopped it). The capture script wrote wherever
`--out` pointed, its docstring suggested `tests/fixtures/recorded/` in this public repository.

*Fix:* `apirecord.py:88 Sanitizer` is an allowlist — only numbers/ids/enums, intervals, item keys rebuilt from safe
parts, macro names, known tag names, function names, stock/project public names and role words survive; every other
string becomes a stable pseudonym (equality semantics preserved: the test replays a sanitized capture and gets the
identical coverage result). `:214 leaks()` re-scans the sanitized output for every original free-text value; the
capture script refuses to write if anything survives, refuses an `--out` inside the Git work tree, writes mode 600
to `~/zabbix-captures/`, and `tests/fixtures/recorded/` is git-ignored. Replay reads `NETALERT_RECORDED_DIR`.
Committing a capture requires an independent confidentiality review — never automatic.
`netbox.py:77` refuses a repeated page URL, `:88` an empty page with a `next` link, `:28` caps at 1000 pages.

## Test evidence

| Run | Result |
|---|---|
| New `tests/test_followup_rc2.py` (33 tests, many with sub-tests) on rc3 | **33 PASS** |
| Same tests on `31ffc94` (test-support shim only: `exprcheck.py` importable, empty fault-test map) | **all 33 fail** — 43 assertion failures (sub-tests) + 6 errors where the safe API does not exist (`rebuild`, `leaks`, `--record-fault-test`, NetBox loop guard) |
| Full suite, Python 3.13.17 | **298 tests: 297 PASS, 1 NOT RUN** (real-Zabbix replay: no LAB capture) |
| Full suite, CPython 3.9.25 + PyYAML 6.0.3 (RHEL 9 runtime) | **298 tests: 297 PASS, 1 NOT RUN** |
| `scripts/release-gate.sh` (3.8 grammar, unit tests, secret scan incl. history, ShellCheck 0.11) | **PASS** |

Existing tests changed only where rc2 behaviour was itself the defect: utilization fixtures now use the NETOPS policy
triggers (the stock 90 % trigger no longer counts), the mock returns raw expressions + functions like Zabbix does
without `expandExpression`, and PROTECTED tests now record a fault test first.

## What offline tests cannot show — LAB acceptance still required (NO-GO until all pass)

Hypotheses, not verified facts:
1. **Raw `trigger.get`** in Zabbix 7.0 returns `{functionid}` expressions and `selectFunctions` returns `parameter`
   with the `$` item placeholder exactly as modelled; stock templates' link-down/recovery shapes match `exprcheck`
   (otherwise those ports show UNPROVEN — safe, but must be known).
2. **Event/alert fields**: `r_eventid` on problem events; recovery alerts carry `p_eventid` = problem event and
   `userid`; `select_alerts` returns them for a least-privilege token.
3. Dependent-item freshness (NETOPS capacity item → `hspeed` master) behaves as modelled on a real poller.
4. A LAB capture passes the leak check, replays, and `tests.test_recorded_fixtures` passes against it.
5. A real **Problem + Recovery e-mail** fault test in LAB → `--record-fault-test` → PROTECTED; then a change to the
   action or a recipient's media drops it to CONFIG VERIFIED.
6. The documented install → `--setup` → commit → review → commit → `--verify` → `--deploy` and `--update` sequence on
   the RHEL VM through FortiProxy (shallow fetch by SHA from GitHub, `.git/shallow` boundary as the published proof).
7. OSPF/BGP Network Health templates: full LAB acceptance (`docs/NETWORK-HEALTH.md` §8); production stays blocked.

**GO is not claimed.** It requires the real Zabbix API (1–4), the OSPF/BGP templates (7) and the Problem/Recovery
e-mail path (5) validated in LAB, then the production gates in `docs/ONBOARDING.md` §8.

## Addendum — rc4: Zabbix 7.0 API contract (review of rc3 `64387e7`)

Checked against the 7.0 method reference (trigger.get, event.get, host.get, item.get, template.get, action.get,
user.get, usergroup.get, alert object).

| # | Finding | Verdict on 64387e7 | Fix |
|---|---|---|---|
| A1 | `trigger.get selectFunctions` asked for `name`; `rebuild()` read `f["name"]` | **Verified defect, fatal**: 7.0 function objects are `functionid, itemid, function, parameter`. A validating server rejects the request (discovery aborts); a lenient one returns no `name` → `KeyError` in `rebuild()`. Hidden because the rc3 discovery mock (written by me) returned `name`; the v1.0.2 planner (`planner.py:110`) and original mock already used `function` | `discovery.py` requests and reads `function`; an absent/invalid function name becomes `{UNKNOWN}` (fails closed) |
| A2 | `event.get` used `select_alerts` | **Verified**: deprecated in 7.0 (still honoured per the docs, replaced by `selectAlerts`) | `selectAlerts`; an event without an `alerts` property makes history "not readable" (never PROTECTED) |
| A3 | (audit) recovery-alert placement | Not settled by the docs (alert `eventid` = "event that triggered the action") | correlation keys on `p_eventid` = problem event and accepts the alert on the recovery **or** problem event; LAB probe C6 records which |
| A4 | (audit) `action.get` docs example shows `opmessage` as an array (malformed example, PHP `=>` inside) | Live 7.0 returns an object (v1.0.2 LAB acceptance ran `planner.py:196` on it) | `coverage.opmessage()` accepts object or one-element array, anything else fails closed |

Audit result for every other read request: all parameters documented and not deprecated (host, item, template,
action, user, usergroup, trigger, event). Not verifiable from the docs pages and therefore LAB probe items:
`hostgroup_rights` field names, interface `available`/`error`, mediatype/hostgroup/usermacro parameter lists,
`expandExpression` macro behaviour.

Contract tests (`tests/test_api_contract.py`, `tests/zabbix70_contract.py`): every discovery request checked
against the transcribed 7.0 parameter lists, and discovery + correlation run against hand-written,
documentation-shaped responses (not the mock). On 64387e7: 1 failure + 8 errors of 8 tests (contract violations:
`selectFunctions` field `name`, deprecated `select_alerts`); on rc4: 10/10 pass (incl. 2 probe tests).
The discovery mock now rejects undocumented parameters/fields like the API validator and returns `function`.

Read-only LAB procedure and contract probe: `docs/LAB-VALIDATION-v1.1.md`, `scripts/lab-contract-probe.py`.
Feature work stops here; next step is LAB.

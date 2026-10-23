# Independent Final Production Review — Zabbix Interface Alerting-as-Code v1.0.2

| | |
|---|---|
| Reviewer | Claude (independent, read-only) |
| Date | 2026-10-23 (Asia/Riyadh) |
| Repository | `jaber717/Zabbix`, project `zabbix-alerting/` |
| Release under review | tag `v1.0.2` (annotated `e30181a`) → commit `855cd3286decdd96921335de62dfcee39622bdd9` |
| Target | Zabbix 7.0 LTS, isolated Production (no internet), deadline Sunday 2026-10-25 |
| Scope of this review | Code, docs, LAB evidence, offline rehearsal. **LAB and Production were not contacted. Nothing was deployed. No application code or configuration was changed** — this report and `OFFLINE-INSTALL-v1.0.2.md` are the only files added, on review branch `claude/interface-alerting-v1.0.2-production-review` (based on tag `v1.0.2`). |

---

## 1. Verdict

| | Verdict | Basis |
|---|---|---|
| **Code readiness (v1.0.2)** | **GO** | No functional defect found. Tag is published on GitHub and peels to the accepted commit. Parser, planner, applier, action, safety gates and rollback behave as documented in an offline production rehearsal. Remaining items are documentation corrections only. |
| **Production deployment** | **NO-GO — today** | Not a code problem. Every production input is still a placeholder (URL regex, notification action, inventory, token), the documented install path assumes internet access, and the Email notification path has never executed on any Zabbix. All are closable in one working day (section 6). Becomes GO only when the evidence in section 7 exists. |

**The project must not be described as "deployed" or "Production-ready" until section 7 is complete.**

---

## 2. Release and repository status (verified, not assumed)

| Fact | Evidence |
|---|---|
| Tag `v1.0.2` exists on GitHub | `git ls-remote origin refs/tags/v1.0.2` → `e30181a…`, peeled `855cd32…` |
| Tag created after acceptance | tagger date 2026-10-08 19:01 +03; Codex acceptance commit `4260b13` at 18:54 +03 |
| Tag annotation | "Independent acceptance: APPROVED WITH LIMITATIONS (Codex, evidence 4260b13). Limitations: ShellCheck not run; live rollback not tested; LAB SNMP freshness not provable." |
| Code on acceptance branch == tag | `git diff 855cd32 origin/codex/interface-alerting-v1.0.2-acceptance` = one added evidence file, no code |
| Default branch | `staging` — **does not contain `zabbix-alerting/`**; neither does `main`. v1.0.2 is reachable only via the tag and the `claude/`/`codex/` branches. Install by tag (as the guide already does). Do not use `main`/`staging`. |
| Previous tags | `v1.0.0`, `v1.0.1` immutable; `v1.0.1` failed acceptance (uncompilable `scripts/ingest-handover.py`), superseded |

---

## 3. Confirmed completed work

Only items backed by evidence. "Reproduced" = re-run by this reviewer on 2026-10-23.

### 3.1 Reproduced in this review
| Item | Result |
|---|---|
| Unit suite, fresh clone at `v1.0.2` | **182/182 PASS** (Python 3.13, PyYAML 6.0.3) |
| `scripts/release-gate.sh` (syntax 63 Python / 34 shell, tests, secret scan incl. history) | **PASS** |
| ShellCheck 0.11.0 `-S warning` (previously NOT RUN everywhere) | `apply.sh` **clean**. 3 × SC2164 (`cd` without `|| exit`) in `scripts/lab-write-test.sh` and `scripts/secrets-scan.sh` — LAB/dev scripts, not on the production path. No fix required for Production. |
| Minimum Python (static scan, `vermin`) | runtime `netalert/` + `scripts/lab_verify_objects.py`: **3.4+**; only the dev gate `scripts/check-syntax.py` needs 3.8. Not executed on 3.6. |
| Offline **production rehearsal**: shipped `production.yaml` with a real-shaped `url_regex` and an Email `alert_action`, a 4-interface ISP+P2P inventory, the real CLI against the repository's Zabbix 7.0 API model | See 3.2 |
| Offline transfer: `git bundle` of tag → clone → `checkout -b prod-local v1.0.2` → tests | **PASS** — bundle 508 KB, tag preserved, HEAD `855cd32`, 182/182, `--check` fails closed without production variables (exit 2) |

### 3.2 Offline production rehearsal — sequence and results
| Step | Exit | Behaviour |
|---|---|---|
| `--check` (unclaimed server) | 0 | 4/4 PASS, load estimate printed |
| `--dry-run` | 0 | 85 ADD: identity, template (1 LLD, 9 item / 28 trigger prototypes), 2 links, macros, action — **no writes** |
| apply without `--init-identity` | 3 | refused: unclaimed Zabbix |
| `--init-identity` without `--confirm` | 3 | refused |
| `--init-identity --confirm production` | 0 | `{$NETOPS.ENVIRONMENT}=production` created |
| apply without `--confirm` | 3 | refused, plan shown |
| `--confirm production` | 0 | backup written, 84 changes, **"verification plan is empty"** |
| `--dry-run` | 0 | **"No changes required."** (idempotent) |
| Action created | — | 1 condition: event tag `netops_alert`; **Problem op** and **Recovery op** both `send message` to the configured user group, pinned to the `Email` media type ID |
| Rollback to `hosts: {}` without `--allow-empty` | 1 | refused (truncation guard) |
| Rollback with `--allow-empty --confirm production` | 0 | 82 REMOVE (unlink+clear, macros only), then "No changes required." Template, action and identity macro **remain**. |

### 3.3 LAB evidence from Codex (Zabbix 7.0.30) — verified vs. claimed
| Claim | Status | Source |
|---|---|---|
| `--check` PASS 18/18; `--dry-run` "No changes required." on exact `855cd32` | **Verified live** | `codex-v1.0.2-final-lab-acceptance.md` |
| Template content, links, macros, discovery, 72/72 items supported, thresholds 70/65 on 18/18 | **Verified live** | v1.0.1 and v1.0.2 acceptance |
| Link DOWN → Problem, UP → Recovery delivered (Telegram) | **Verified live** (fault injected, first bad poll 2 s after shutdown) | `codex/interface-alerting-telegram:handover/agents/codex-latest.md` |
| RX/TX utilization Problem + Recovery with hysteresis | **Verified live** with temporary 0.05 % / 0.02 % thresholds (mechanism, not 70/65 under real load) | same |
| Action filter isolation (only `netops_alert`) | **Verified live** | same |
| `VERIFICATION INCOMPLETE` fail-safe | Offline tests only (4 focused tests) | acceptance |
| **Flapping, error-rate, discard-rate, speed-degraded alerts** | **Never fault-injected live.** Logic covered by offline simulator only; LAB interfaces had zero errors/discards | — |
| **Email/SMTP delivery** | **Never executed on any Zabbix.** LAB SMTP path was blocked; LAB used Telegram. | codex-latest.md "Email problem/recovery delivery is blocked" |
| Rollback | Offline only. **Live rollback NOT TESTED** | acceptance |
| SNMP freshness at v1.0.2 acceptance | **Not provable** — all LAB routers unreachable at the time (freshness proven at v1.0.1, same code) | acceptance |
| Production | **Never touched** | all evidence |

### 3.4 Requirement traceability
| # | Requirement | Status |
|---|---|---|
| 1 | Manual inventory in `config/interfaces.production.yaml` | Supported; the CLI selects `config/interfaces.<env>.yaml` automatically. File ships `hosts: {}`. |
| 2 | Email only in Production; Telegram LAB-only | Supported. `production.yaml` has no Telegram; `media_type` pins the action to one named media type. |
| 3 | Reuse existing SMTP | Supported — the tool references the media type **by name** and never creates/edits media types or users. |
| 4 | Selected interfaces incl. ISP and P2P | Supported; `role` is a free label (ISP/P2P), `link_id` correlates both ends. |
| 5 | 70 % Problem / 65 % Recovery | Supported (built-in values), **but utilization is `enabled: false` by default** — must be enabled (section 5.2). |
| 6 | Preserve existing templates/triggers/hosts/actions | Met by design: only `{$NETOPS.*}` macros with the ownership marker, template `NETOPS Interface Alerting`, action `NETOPS-IaC …` and one global macro are written. Stock templates and actions are never modified. Behavioural overlap: see L1. |
| 7 | Simple install, preferably from GitHub | Simple, but **direct GitHub clone is impossible in an isolated network** (C2). Bundle transfer verified. |
| 8 | No extra services/DB/GUI | Met: `git`, `python3`, PyYAML; no daemon, no DB; uses the Zabbix API only. |
| 9 | No production change without approval | Met technically: every write needs `--confirm production`; `--check`/`--dry-run` use a client that refuses write methods. Approval is a process gate (section 6). |

---

## 4. Blockers (actual only)

### Critical
**C1 — Production inputs do not exist yet (tool will refuse to run until they do).**
`zabbix.url_regex` is the fail-closed placeholder, `alert_action` is commented out (without it **no notification is sent at all**), inventory is empty, no token exists. Fix: fill exactly the inputs in section 5. No code change.

**C2 — Documented install path does not work in an isolated network.**
`docs/PRODUCTION-INSTALL.md` §1 runs `git clone https://github.com/…` and `dnf install` from the target. Fix (verified in this review): create a `git bundle` of the tag on a connected machine, transfer it with its SHA-256, clone from the bundle (commands in section 6; full procedure in `docs/OFFLINE-INSTALL-v1.0.2.md`). The bundle keeps the tag and history, so the guide's update and rollback procedures (`git merge`, `git checkout <commit> -- …`) keep working. `python3` + PyYAML must come from the host or the internal RHEL repo (`python3-pyyaml` is a standard RHEL package).

### High
**H1 — Email delivery is unproven on any Zabbix.**
Only Telegram was delivered in LAB. Fix: one controlled Problem + Recovery in Production through the tool itself, without touching any device — temporarily lower the utilization threshold of one non-critical selected interface below its current load, apply, receive both e-mails, restore 70/65, apply (section 6, step 9). Requires approval (it is a production change).

**H2 — Recipients can be silently skipped.**
Zabbix sends nothing to a user who (a) has no enabled Email media, (b) whose media severity filter excludes High/Disaster, or (c) whose user group lacks **read permission on the host groups** of the selected hosts. The action will look correct and still deliver nothing. Fix: verify in the UI before apply (read-only check; section 5.1).

**H3 — The guide's API-account advice is wrong for one step.**
`PRODUCTION-INSTALL.md` suggests a custom role that "may create global macros". In Zabbix 7.0 `usermacro.createglobal` is Super admin only, so `--init-identity` fails with any Admin-type role. Fix: use a dedicated **Super admin** service user's API token (same as LAB), or a Super admin token for the one-time `--init-identity` and an Admin token afterwards. Doc fix: one line.

**H4 — TLS (conditional).**
Production uses `verify_tls: true` and Python's system trust store. If the frontend has an internal/self-signed certificate, every call fails as `Zabbix API unavailable`. Fix: install the CA into the host trust (`/etc/pki/ca-trust/source/anchors/` + `update-ca-trust`), or add `SSL_CERT_FILE=/path/ca.pem` to `.env`. Do **not** set `verify_tls: false`. If the frontend is plain `http://`, set the URL and `url_regex` accordingly.

### Low
**L1 — Notification overlap with existing actions/stock triggers (decision, not a defect).** Any existing production action whose conditions do not exclude these new triggers (e.g. a catch-all "all problems ≥ High → NOC") will also e-mail NETOPS problems → duplicates. Stock interface triggers (link down via `{$IFCONTROL}`, high bandwidth at `{$IF.UTIL.MAX}`, error rate) stay active by design (`suppress_stock: false`), so one outage can raise two problems. Smallest fix: none in code; list existing action conditions (read-only) and decide to accept duplicates. Do not modify existing actions without separate approval.

**L2 — Rollback.** Not live-tested. First-deployment rollback (`hosts: {}` + `--allow-empty`) removes host links (and the discovered items/triggers) and macros, but leaves the template, the action and `{$NETOPS.ENVIRONMENT}` (confirmed offline). Full uninstall = additionally delete those three in the UI. Undocumented; add one line.

**L3 — Untested alert types.** Flapping, error/discard rate and speed-below-expected were never fault-injected. Not required for go-live; state it honestly in the handover.

**L4 — Documentation drift (no behavioural impact).**
- `RELEASE-v1.0.2.md` line 3 still says "CANDIDATE. Not published, not tagged" — it is tagged and published.
- `README.md` "What alerts" paragraph says "only one end has `notify: true`" — `notify` is rejected by the parser; both ends notify (correct statement is two paragraphs earlier).
- `docs/DESIGN.md` says "`alert_action` stays unset in `lab.yaml`" — it is set (Telegram).
- `PRODUCTION-INSTALL.md`: C2, H3, L2, and §5 `git commit` needs `git config user.name/user.email` on the production host.

**L5 — Python 3.6 hosts (conditional).** On RHEL 8 `/usr/bin/python3` is 3.6. Runtime code scans as 3.4-compatible (not executed), but `tests/test_python_syntax.py` needs 3.8, so the guide's "sanity" unit-test step fails there. Prefer `python3.9`/`python3.11` with its PyYAML package via `PYTHON=python3.9 ./apply.sh …`; otherwise skip the unit tests on that host (they already passed on the tag).

**L6 — Interface name source.** `--check` validates names against the stock items' `interface` tag; the tool's own discovery uses `ifName` (`1.3.6.1.2.1.31.1.1.1.1`). They agree for standard 7.0 SNMP templates. If a vendor template tags by another field, `--check` can PASS and nothing is discovered. Caught by `scripts/lab_verify_objects.py` ("discovered interfaces == YAML") — make its output mandatory evidence.

**L7 — E-mail body is plain text with CRLF.** If the production Email media type is set to HTML, line breaks collapse. Check the media type's message format is plain text.

No security gate, refactor, dependency or feature is recommended.

---

## 5. Exact missing inputs

### 5.1 Environment (`.env`, `config/environments/production.yaml`)
| Input | Where | Note |
|---|---|---|
| Production frontend URL (scheme, host, path) | `.env` `ZABBIX_URL_PRODUCTION` | Must not contain `lab`, `test` or `dev` (`forbid_url_regex`). `/api_jsonrpc.php` is appended automatically. |
| URL regex matching only that URL | `production.yaml` `zabbix.url_regex` | e.g. `'^https://zabbix\.corp\.local(/zabbix)?/?$'` — case-sensitive, matched against the `.env` value |
| API token of a dedicated **Super admin** service user | `.env` `ZABBIX_TOKEN_PRODUCTION` | `chmod 600 .env`; leave LAB values empty on this host |
| CA certificate (if HTTPS with internal CA) | host trust store or `SSL_CERT_FILE` | H4 |
| Server version 7.0.x | confirmed by the tool | Anything else is refused |
| Exact media type name | `alert_action.media_type` | Administration → Media types (default is `Email`; could be `Email (HTML)` or custom). Message format plain text (L7). |
| Recipient user group name | `alert_action.usergroups` | H2: members have enabled Email media incl. High + Disaster; group has read on the hosts' host groups |
| Deploy host facts | — | OS + `python3 --version`, `python3 -c 'import yaml'`, `git --version`, HTTPS reachability to the API |

Block to add to `production.yaml`:
```yaml
alert_action:
  name: "NETOPS-IaC Interface Alerts"
  enabled: true
  usergroups: ["<exact production user group>"]
  media_type: "<exact production Email media type name>"
```

### 5.2 Inventory (`config/interfaces.production.yaml`) — per interface
| Field | Rule |
|---|---|
| Host key | Zabbix **technical Host name** (Configuration → Hosts → "Host name"), **not** the Visible name |
| Interface key | Exact `ifName` as Zabbix shows it in the item tag `interface` (e.g. `HundredGigE0/0/0/0`, `GigabitEthernet0/0/1`) |
| `site` | per host |
| `description` | **required** |
| `role` | `ISP` or `P2P` |
| `severity` | `warning` / `average` / `high` / `disaster` |
| `link_id` | same value on both ends of a P2P link; unique ID per ISP circuit |
| `expected_speed` | **ISP links where committed rate ≠ port speed:** set to the committed rate (e.g. `1G` on a 10G port). It becomes the capacity for the 70 % calculation and only alerts if the port negotiates *below* it. Omit when port speed is the capacity. |

Host prerequisites (checked by `--check`): host exists and is enabled, has an SNMP interface, stock interface template linked and already discovered.

Recommended file shape — note `defaults.utilization.enabled: true` (built-in default is **false**):
```yaml
defaults:
  severity: high
  utilization: {enabled: true, threshold: 70, recovery: 65}
  # errors/discards default to 1 per second; raise (e.g. rate: 10) per interface if ISP links show constant discards
hosts:
  <EDGE-HOST-1>:
    site: <SITE>
    interfaces:
      <ifName>: {description: <ISP name> Internet, role: ISP, severity: disaster, link_id: ISP-<NAME>-01, expected_speed: <committed>}
      <ifName>: {description: P2P to <EDGE-HOST-2>, role: P2P, link_id: P2P-<ID>}
  <EDGE-HOST-2>:
    site: <SITE>
    interfaces:
      <ifName>: {description: P2P to <EDGE-HOST-1>, role: P2P, link_id: P2P-<ID>}
```
Quote any key containing `:` or starting with a digit-only value.

### 5.3 Process inputs
Named approver for Production writes; a maintenance/change window; one non-critical selected interface with steady traffic for the alert proof (H1).

---

## 6. Minimal commands and one-day checklist

**A. Connected workstation (≈10 min)**
```bash
git clone https://github.com/jaber717/Zabbix.git && cd Zabbix
git rev-parse 'v1.0.2^{commit}'                 # must print 855cd3286decdd96921335de62dfcee39622bdd9
git bundle create ../zabbix-alerting-v1.0.2.bundle v1.0.2
sha256sum ../zabbix-alerting-v1.0.2.bundle      # record; transfer bundle + hash via approved media
```

**B. Production deploy host — read-only preparation (no approval needed)**
```bash
sha256sum zabbix-alerting-v1.0.2.bundle         # must equal recorded hash
git clone zabbix-alerting-v1.0.2.bundle Zabbix  # "remote HEAD … nonexistent ref" warning is expected
git -C Zabbix checkout -b prod-local v1.0.2
git -C Zabbix rev-parse HEAD                    # 855cd3286decdd96921335de62dfcee39622bdd9
cd Zabbix/zabbix-alerting
python3 -c 'import sys, yaml; print(sys.version)'   # 3.8+ preferred (L5)
python3 -m unittest discover -s tests -t .          # expect 182 OK (skip on 3.6)
cp .env.example .env && chmod 600 .env && vi .env   # PRODUCTION pair only
vi config/environments/production.yaml              # url_regex + alert_action (5.1)
vi config/interfaces.production.yaml                # inventory (5.2)
./apply.sh --env production --check                 # every line PASS, RESULT: PASS
./apply.sh --env production --dry-run               # review ADD list; save output for approval
```
Stop on any `FAIL`, `REVIEW REQUIRED`, `IDENTITY MISMATCH`, `VERIFICATION INCOMPLETE`.

**C. Production writes — only after explicit approval of the dry-run output**
```bash
./apply.sh --env production --init-identity --confirm production
./apply.sh --env production --confirm production    # last line: verification plan is empty
./apply.sh --env production --dry-run               # No changes required.
python3 scripts/lab_verify_objects.py --env production --config config/interfaces.production.yaml   # RESULT: PASS
git -C .. add zabbix-alerting/config && git -C .. -c user.name="<you>" -c user.email="<you>" commit -m "production config v1.0.2"
```

**Checklist (target Saturday 2026-10-24, buffer Sunday)**
| # | Task | Owner | Done when |
|---|---|---|---|
| 1 | Create bundle + hash, transfer | Engineer | hash matches on target |
| 2 | Confirm python3/PyYAML/git on deploy host | Engineer | commands in B print versions |
| 3 | Create Super admin service user + API token | Zabbix admin | token in `.env` |
| 4 | Read-only checks in UI: media type name + plain-text format; recipient group, members' Email media + severities, host-group read permission; existing actions' conditions (L1) | Zabbix admin | 5.1 table filled |
| 5 | Fill `production.yaml` and inventory (all ISP + P2P interfaces, `expected_speed` for ISPs) | Engineer | `--check` RESULT: PASS |
| 6 | `--dry-run`, send output to approver | Engineer | written approval |
| 7 | Init identity + apply | Engineer (approved) | "verification plan is empty" |
| 8 | Idempotency + object verifier | Engineer | "No changes required." + verifier RESULT: PASS |
| 9 | **Email proof**: on one selected interface set `utilization: {enabled: true, threshold: <below current %>, recovery: <lower>}` (e.g. 1 / 0.5) → `--dry-run` (2 macro CHANGEs) → apply → Problem e-mail within ~1 min (config-cache sync + next 10 s poll) → restore 70/65 → apply → Recovery e-mail → `--dry-run` = No changes required | Engineer (approved) | both e-mails received, Zabbix alert log "Sent" |
| 10 | Commit production config on `prod-local`; archive outputs | Engineer | commit hash recorded |

Rollback at any point: `git checkout <last-good> -- config/interfaces.production.yaml` → `--dry-run` → `--confirm production`. Before any good commit exists: `hosts: {}` + `--allow-empty --confirm production`, then delete template `NETOPS Interface Alerting`, action `NETOPS-IaC Interface Alerts` and global macro `{$NETOPS.ENVIRONMENT}` in the UI for a full removal. Every apply writes `state/backups/production-<time>.json` first.

---

## 7. Evidence required to declare Production successful

All of the following, captured as text/screenshots and filed with the change record:

1. Bundle SHA-256 on both sides; `git rev-parse HEAD` = `855cd32…` on the deploy host.
2. `--check` output: every interface PASS, `RESULT: PASS`, interface count equals the approved inventory.
3. Approved `--dry-run` output and the approval reference.
4. Apply output ending `RESULT: applied N change(s); verification plan is empty.` plus the backup filename.
5. Second `--dry-run`: `No changes required.`
6. `scripts/lab_verify_objects.py --env production …`: `RESULT: PASS` (identity, template content, links, macros, **discovered interfaces == YAML**, values arriving, no unsupported items, trigger instances).
7. Action `NETOPS-IaC Interface Alerts` in UI: enabled, single condition tag `netops_alert`, Problem and Recovery operations to the intended group via the production Email media type.
8. **One Problem and one Recovery e-mail received** by a recipient, plus Reports → Action log entries with status Sent, zero retries.
9. Final state after the test: thresholds 70/65 on all interfaces, no open NETOPS test problem, `--dry-run` = No changes required, production config committed on `prod-local`.
10. Confirmation that no stock template, trigger, host or existing action was modified (the apply output lists only NETOPS objects).

Until items 1–10 exist, the status is **"code released, Production pending"**.

---

## 8. Management summary

The Interface Alerting-as-Code solution (release v1.0.2) is complete and released. It lets the network team define, in a single reviewed file, exactly which ISP and point-to-point interfaces must alert, and applies that to Zabbix 7.0 in three commands: check, preview, apply. It alerts on link down/up, utilization above 70 % (clearing below 65 %), error and discard rates, link flapping and speed degradation, and sends both problem and recovery e-mails through the existing Production mail configuration. Existing monitoring, templates and alert rules are not changed, no new servers or databases are required, and every Production change requires explicit confirmation.

The software passed 182 automated tests and independent acceptance in the lab, where real link-failure and utilization alerts were delivered end-to-end. Production deployment remains open: it needs the Production interface list, access credentials and recipient details, a one-time offline transfer of the package, and a controlled test proving e-mail delivery. These are configuration tasks estimated at one working day and can be completed before Sunday, 25 October 2026, subject to change approval.

# Codex - LAB Interface Alerting end-to-end validation

Validated 2026-10-08 against Zabbix 7.0.30 at the LAB endpoint only.

## Git context

- Validation branch: `codex/interface-alerting-lab-validation`
- Frozen framework source: `claude/noc-flow-platform` at `9e16bd352df07c4e5f72a25689128e81d5b40d73`
- Framework source was not redesigned or modified during this validation.
- Offline regression suite: 136/136 PASS on Windows and 136/136 PASS on the RHEL Zabbix VM.

## SNMPv3

- Root cause confirmed: the old shared SNMPv3 passphrases in Zabbix did not match the router-side localized keys. SITE-A counters showed wrong SHA digests and unknown engine IDs, with no unknown-user failures.
- All seven Zabbix hosts used the same policy: per-host macros, `authPriv`, SHA, AES128. The interfaces referenced `{$SNMPV3_USER}`, `{$SNMPV3_AUTH_PASS}`, and `{$SNMPV3_PRIV_PASS}`.
- Router-side `ZBX-GRP`, `ZBX-RO`, and the `ZBX-SNMP-SOURCE` access restriction were valid.
- Credential rotation performed: **YES**. An additive user, `zbxv3lab2`, was created on all seven routers. The old user was retained as a fallback.
- New passphrases are protected by host-encrypted, root-only system credentials on the LAB Zabbix VM. No secret value is present in Git or this handover.
- Router configurations were saved after the new account passed direct polling and Zabbix recovered.

| Router | Management IP | Direct SNMPv3 | Required OIDs | Zabbix availability |
|---|---:|---|---|---|
| SITE-A | 192.168.1.180 | PASS | PASS | PASS |
| SITE-B | 192.168.1.181 | PASS | PASS | PASS |
| STC | 192.168.1.182 | PASS | PASS | PASS |
| MOBILY | 192.168.1.183 | PASS | PASS | PASS |
| INT-CORE | 192.168.1.184 | PASS | PASS | PASS |
| SAIX-A | 192.168.1.186 | PASS | PASS | PASS |
| SAIX-B | 192.168.1.187 | PASS | PASS | PASS |

Direct tests from 192.168.1.91 covered sysName, sysUpTime, ifName, ifOperStatus,
ifHCInOctets, ifHCOutOctets, and ifHighSpeed. Seven-OID test time was 458-523 ms per router.

## 18-interface freshness

- Final result: **18/18 PASS**.
- All seven hosts were SNMP available with no authentication error.
- Every selected interface resolved to the handover index: Gi0/0=index 1, Gi0/1=index 2, SITE-A/SITE-B Gi0/2=index 3, and SITE-A/SITE-B Gi0/3=index 4.
- `netops.if.oper`, `netops.if.in`, and `netops.if.out` were supported and fresh inside the 10-second policy window.
- `netops.if.speed` was supported and fresh inside the 60-second policy window.
- Every item carried the correct resolved `interface=<ifName>` tag.

## Real framework apply

- `--check`: PASS, 18/18 interfaces.
- Initial `--dry-run`: safe plan, 365 ADD / 0 CHANGE / 0 REMOVE.
- Real import/apply: functional PASS. The managed template, 356 owned host macros, seven template links, and LAB identity were created through the supported API.
- Final policy values: 18/18 interfaces at problem 70%, recovery 65%.
- Final active managed problems: 0.
- Real idempotency result: **DRIFT** due to the comparator defect below. The final dry-run reports only one false template change; host links and macros are clean.

## Real event tests

### Link Down / recovery

- Test interface: SAIX-B Gi0/0 toward SAIX-CORE. Management remained reachable.
- First bad indexed poll: PASS, 2 seconds after shutdown (inside one 10-second polling interval).
- Zabbix problem: PASS, event 10865, Disaster severity (5), `link_id=saix-core--saix-b`.
- Interface restored immediately; Zabbix status returned UP and event 10865 has a recovery event.
- A preliminary transport-only test on SAIX-A Gi0/0 was also restored immediately; it was not counted as formal event evidence.

### RX / TX utilization and hysteresis

- Test interface: SAIX-A Gi0/0 toward SAIX-CORE.
- Temporary LAB-only policy: problem 0.05%, recovery 0.02%; changed through the framework config path.
- Above threshold: RX 865,790 bps and TX 865,831 bps; both problems opened.
- Between thresholds: RX 432,876 bps and TX 432,991 bps; both problems remained open.
- Below recovery: RX 0 bps and TX 52 bps; both problems recovered.
- Final framework apply restored 70/65 and API verification confirmed 18/18 interfaces use the final policy.

## Notifications

- Built-in Email and HTML Email media types are disabled and not configured with a real SMTP target.
- Gmail, Gmail relay, and Office365 definitions are disabled examples; no validated credential path exists.
- `Report problems to Zabbix administrators` is disabled but contains both problem and recovery operations.
- External problem notification: BLOCKED by missing enabled/validated SMTP credentials.
- External recovery notification: BLOCKED by the same SMTP limitation.
- No mail credential was invented and no existing notification object was destroyed.

## Stock trigger verification

- `Cisco IOS by SNMP` was exported through the API and inspected.
- Its stock Link Down prototype problem expression requires `{$IFCONTROL:"{#IFNAME}"}=1`.
- Its recovery expression includes `{$IFCONTROL:"{#IFNAME}"}=0`.
- `suppress_stock=false` remains unchanged as required.

## Final router health

- All 18 selected interfaces are up/up.
- BGP is healthy on all seven routers after testing.
- Five-second CPU observed between 4% and 13%.
- Selected interfaces have zero input errors, output errors, and output drops.
- No traffic generator remains running and no interface remains shut.

## CLAUDE ACTION REQUIRED

The real second dry-run is not clean because `planner.live_fingerprint()` reads
`triggerprototype.get.expression` and `recovery_expression` directly. On Zabbix
7.0.30 these live strings contain internal function references such as `{37176}`
and `{37177}`, while the desired fingerprint contains semantic expressions such
as `last(/NETOPS Interface Alerting/netops.if.oper[{#SNMPINDEX}])` and
`changecount(...)`. Consequently all 28 desired triggers are reported missing
and all 28 live triggers unexpected after every successful import.

- Exact result: `CHANGE template NETOPS Interface Alerting re-import (triggers: 28 missing, 28 unexpected)`.
- Implicated code: `zabbix-alerting/netalert/planner.py::live_fingerprint()` and the live-expression normalization used by `netalert/template.py`.
- Minimal fix: fingerprint the live template from `configuration.export` (normalizing an omitted empty macro `value` to `""`), or reconstruct semantic expressions from `selectFunctions`; do not compare raw internal function IDs with import syntax.
- Add a regression using a real Zabbix 7.0-style trigger response containing function IDs, then prove the second live dry-run says `No changes required.`
- This is an idempotency/comparison defect, not a failed import: live indexed items and real Link Down, recovery, RX, TX, and hysteresis events all passed.

## Remaining blockers

1. Framework false template drift prevents a clean real idempotency result.
2. Email problem/recovery delivery is blocked only by the absence of an enabled, validated SMTP credential path.

## 2026-10-08 - Telegram notification handoff

- Work continues on `codex/interface-alerting-telegram`, based on Claude's semantic-comparison commit
  `423e9de9c8f327fe9132b18e1b39f70ec0bcb570`; Claude's branch was not rewritten.
- Live prerequisites: existing `Telegram` media type enabled; Admin's existing Telegram media enabled for all
  severities and the full weekly period; destination is configured. No duplicate media type was created.
- The LAB environment now declares the managed `NETOPS-IaC Interface Alerts` action using only `Telegram` and
  the existing `Zabbix administrators` group. The action condition is solely the framework-owned event-tag key
  `netops_alert`; stock triggers do not carry this key.
- Problem and recovery messages include host, site, `link_id`, interface/description/role, event severity,
  managed alert type, direction, configured threshold, and trigger operational data (including utilization
  sample/capacity for utilization events).
- Live API validation found that recovery operation type 11 (`notify all involved`) rejects `mediatypeid` on
  Zabbix 7.0.30. The focused correction uses a recovery `send message` operation (type 0) with the same group
  and explicit Telegram media type. Offline regression suite: 151/151 PASS. A disabled live action (ID 7) was
  created through the API and its exact filter, recipients, Telegram-only problem/recovery media, immediate
  problem step, and message fields were verified. It remains disabled pending the security gate below.
- Security gate: the operator must explicitly confirm that the previously exposed Telegram bot token was
  rotated and that the replacement token passed a media-type test. Token contents must never enter Git/chat.
  Do not enable the action or run Link Down/utilization delivery tests before this confirmation.
- Separate pre-existing issue: the current live dry-run with commit 423e9de reports one template change with
  `triggers: 8 missing, 0 unexpected`. This was deliberately not applied as part of notification setup.

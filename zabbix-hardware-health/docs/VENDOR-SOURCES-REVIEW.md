# Vendor source review (v0.3.1-rc2, 2026-10-09)

Only verified sources are used; nothing is invented. "Verified" below says exactly what was checked and how. NOTHING here is a real-device verification.

## 0. Method: definitions are checked against the MIB text, offline, by tests

| Vendor | Source of the check | Pinned | Test |
|---|---|---|---|
| Cisco IOS-XE, Nexus | the **Cisco-published** MIB files `CISCO-ENVMON-MIB`, `CISCO-ENTITY-FRU-CONTROL-MIB`, `CISCO-ENTITY-SENSOR-MIB` (github.com/cisco/cisco-mibs, `v2/`) | commit `c9ab98c0...5e91` + SHA-256 of each file in the extract | `tests/test_v03rc2_cisco_mibs.py::CiscoMibs` |
| Fortinet FortiGate | `FORTINET-FORTIGATE-MIB` as mirrored by LibreNMS (**third-party mirror**, labelled so) | LibreNMS `bcfb3b45...` | `FortinetHuaweiMibs` |
| Huawei VRP | `HUAWEI-ENTITY-EXTENT-MIB` / `HUAWEI-MIB` as mirrored by LibreNMS (**third-party mirror**) | same commit | `FortinetHuaweiMibs` |
| Palo Alto | the official Zabbix 7.0 template `Palo Alto PA-440 by HTTP` (no public MIB: XML API) | `4a89781b...` + SHA-256 of the template file | `tests/test_v03rc2_pan_auth.py` |

`docs/sources/extract-cisco-mibs.py` / `extract-vendor-mibs.py` resolve every OID by following the `::= { parent n }` chain from the MIB text and extract the `INTEGER {...}` enumerations; the tests require that **every OID in every definition equals the MIB-derived OID and that every raw value and its meaning name equals the MIB's enumeration** (`unknown/up/down/warning`, the twelve `PowerOperType` values, `normal ... notFunctioning`, `ok/unavailable/nonoperational`, Fortinet `false/true` and `unsynchronized/synchronized`, Huawei `normal/abnormal`). Result: all pass; no OID or enumeration had to be corrected. *Classification* (which meaning is `failed` vs `degraded`) is a project decision documented in each definition; it is not something a MIB can verify.

## 1. Cisco "ASR 8500" / IOS-XR - still BLOCKED, now precisely documented

* Cisco's pages describe **no product named "ASR 8500"** (search of cisco.com, 2026-10-09). They describe the ASR 9000 (IOS XR), ASR 1000 / 903 (IOS XE) and the **Cisco 8500 Series Secure Routers** (8550-G2, 8570-G2). The operator must confirm which device is meant.
* For an **ASR 9000 / IOS XR** device the ASR 9000 MIB Specification Guide is *reported* (via search results; fetching the page returned HTTP 504, so this was **not read directly**) to list `CISCO-ENTITY-FRU-CONTROL-MIB` as supported with a "MIB Constraints" section; a Cisco community article is reported to state that power-supply data is admin-restricted (SystemOwner view) and that `entSensorValueTable` is supported but `entSensorThresholdTable` is not; 2016 field reports describe incomplete fan/power data on an ASR 9006.
* The objects themselves (`cefcFanTrayOperStatus`, `cefcFRUPowerOperStatus`) are MIB-verified (section 0), but **which rows an IOS XR chassis returns is not documented**, so no definition is created. If the operator confirms an IOS XR target, a definition can reuse the verified semantics after a device walk shows the rows and the entity-class filter.
* Result: `vendors/cisco-asr8500.yaml` has no sensors; the reasons were made specific.

## 2. FortiProxy - still BLOCKED, now precisely documented

* **Verified** (FortiProxy 7.2.8 administration guide, "Fortinet MIBs"): SNMP needs `FORTINET-CORE-MIB` and `FORTINET-FORTIPROXY-MIB`; the page's only OID is `fchSysVersion` = `1.3.6.1.4.1.12356.109.4.1.1.0`, i.e. FortiProxy has its **own arc `12356.109`**, distinct from FortiGate's `12356.101`.
* **Not found**: any fan / power-supply / temperature object for FortiProxy. The page lists none; `FORTINET-FORTIPROXY-MIB` is **not** in the public LibreNMS mirror; Fortinet's own FortiGate sensor article says the sensor OID structure is specific to FortiGate and does not mention FortiProxy.
* *Reported, not verified*: a CLI command `diagnose hardware sysinfo sensor-status` shows hardware sensors on FortiProxy.
* Needed to proceed: the `FORTINET-FORTIPROXY-MIB.mib` file from Fortinet support (or a device walk of `1.3.6.1.4.1.12356.109`). FortiGate OIDs are **not** assumed.

## 3. Palo Alto PAN-OS XML API - authentication verified against the exact cited template

Extract: `docs/sources/pan-pa440-http-extract.json` (commit `4a89781b...`, SHA-256 of the template file recorded; produced by `docs/sources/extract-pan-auth.py` with `yaml.safe_load`). For both cited commands (`show system environmentals`, `show high-availability all`) the generated HTTP-agent items equal the reference on: `type` HTTP_AGENT, `authtype` **BASIC**, username/password/url/timeout/proxy macros (renamed `{$PAN.PA440.*}` -> `{$NETOPS.HW.API.*}`), `query_fields` (`type=op`, `cmd=<xml>`), `status_codes` empty, `XML_TO_JSON` preprocessing; the password macro is `SECRET_TEXT` and empty; default timeout `15s`. Palo Alto documents Basic authentication for the XML API (cited by Codex). The reference README additionally requires a role with *XML API: Configuration + Operational Requests* and no CLI/REST access for a limited user.

Divergences found while reading the template and **fixed**: (a) the reference creates the HA items through a discovery **singleton** gated on `response.result.enabled = yes`, so a standalone firewall has no HA item; the earlier definition created a plain item that would go *unsupported* on non-HA firewalls - now gated the same way (ES5-only JavaScript, Duktape-safe); (b) the reference raises High for `suspended` but suppresses a suspension caused by an administrator request via `state-reason`; this definition does not read the state reason, so `suspended` is now **degraded (Warning)** instead of failed, and says so; (c) the optional proxy macro was added.
*Still not verified*: real authentication, privileges and response shape on a physical firewall; secret-macro provisioning; `tentative` is alarmed in both HA modes (the reference suppresses it in Active-Passive with an override).

## 4. `auditlog_mode` (inherited evidence assumption) - corrected

Zabbix 7.0 documents `auditlog_mode` as "whether to enable audit logging of low-level discovery, network discovery and autoregistration activities performed by the server (System user)". The v0.2.4 evidence code treated `auditlog_mode != 1` as "not log-all-changes" and returned INCONCLUSIVE. That reading was wrong: the setting does not affect logging of user changes to an action. Only `auditlog_enabled` gates the evidence now; a change of `auditlog_mode` no longer breaks continuity. Tests: `test_auditlog_mode_is_not_an_evidence_gate`, `test_auditlog_mode_change_record_does_not_break_continuity`.

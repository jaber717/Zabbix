# Release v1.1.0 — Discovery-assisted onboarding (CANDIDATE rc4)

**Status: CANDIDATE, NO-GO for production. Not tagged, no GitHub Release, not merged, not deployed.** rc1 (`98bd925`)
received an independent CONDITIONAL NO-GO (fixed in rc2, `docs/REMEDIATION-v1.1.md`); the follow-up review of rc2
(`31ffc94`) found five more defects, all verified and fixed in rc3 with regression tests that fail on rc2 — see
`docs/REMEDIATION-v1.1-rc3.md` (findings with file/line references, LAB hypotheses, remaining gates). rc4 fixes two
Zabbix 7.0 API-contract defects found in rc3 (addendum in the same report). Next step is the read-only LAB procedure,
`docs/LAB-VALIDATION-v1.1.md`; no further features. The rc1 notes below are kept for history.

Tag `v1.0.2` is unchanged and remains the only accepted release. Builds on the v1.0.3 proposal (Network Health, untested).

## What changes for the operator

Before: type every host, interface, role, severity, threshold and both ends' `link_id` into YAML.
Now: `./onboard.sh --env production` discovers (read-only), suggests, you approve in the terminal, it writes both
inventories, audits coverage and gates deployment. Details: `docs/ONBOARDING.md`.

| Component | Change |
|---|---|
| Interface Alerting (`apply.sh`, `netalert/` core, template, schema, environments) | **unchanged** |
| Network Health (`apply-health.sh`, `nethealth/`) | unchanged (still UNTESTED, see `RELEASE-v1.0.3.md`) |
| New | `onboard.sh`, `netalert/{discovery,netbox,onboarding,review,coverage,onboard_cli}.py`, `examples/onboarding-rules.example.yaml` |
| Fixes | `scripts/secrets-scan.sh`, `scripts/lab-write-test.sh`: SC2164 — the release gate failed whenever ShellCheck was installed |
| Evidence | `handover/agents/codex-v1.0.2-final-lab-acceptance.md` brought into this lineage (cherry-pick of `4260b13`) |
| Docs | `docs/ONBOARDING.md`, `docs/TECHNICAL-HANDOVER-v1.1.md` |

## Executed tests (offline, in-memory Zabbix 7.0 model — not a real server)

| Gate | Result |
|---|---|
| `scripts/release-gate.sh`: syntax (3.8 grammar), unit tests, secret scan incl. history, ShellCheck 0.11 | **PASS** |
| Unit tests on Python 3.13.17 | **228 PASS** (182 existing + 46 new) |
| Unit tests on CPython 3.9.25 + PyYAML 6.0.3 (RHEL 9 runtime) | **228 PASS** |
| Mutation: a write injected into discovery | refused by the read-only client; the read-only tests fail as they must |

Covered scenarios (`tests/test_onboarding.py`): empty Zabbix; hosts without ports / without SNMP; missing SNMP data;
stale data and SNMP unavailable; unsupported items; duplicate interface names; changed ifIndex (gate fails until
re-approved); unmatched P2P endpoints; similar names never paired; NetBox cable pairing; preservation of existing
entries and defaults; idempotent rewrites; exclusions persist; explicit removal; no automatic `disaster`; identity
mismatch stops before discovery; unclaimed server cannot deploy; a deny in any user group wins; unexpected API failure writes nothing; permission gaps
reported; hand edits block deploy; vanished approved port blocks deploy; production deploy requires `--confirm`;
deploy through the real `apply.sh` path, then idempotent re-run and PROTECTED classification through the NETOPS
e-mail action; empty inventory never auto-removes; invalid existing inventory is never rewritten; first-run setup
(`.env` mode 600, URL guard); action-filter evaluation (and/or, custom formula, unsafe formula rejected).

## Not validated (production gates)

See `docs/ONBOARDING.md` §8. In short: first read-only run against LAB and Production, confirmation of stock item
conventions, token permissions, network-owner review, deployment, a real Problem + Recovery e-mail, post-deploy
PROTECTED audit, and all Network Health LAB validation. Do not call this production-ready before those pass.

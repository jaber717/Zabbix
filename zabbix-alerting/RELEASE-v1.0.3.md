# Release v1.0.3 — Interface Alerting + Network Health (PROPOSED)

**Status: PROPOSED, NOT TAGGED, NOT PUBLISHED as a GitHub Release. Network Health is UNTESTED.**
No tag `v1.0.3` exists. Tag `v1.0.2` is unchanged and remains the only accepted release.
Nothing in this update was executed against LAB or Production; no unit, integration or LAB test was run for it.

## What is in v1.0.3

| Component | Status |
|---|---|
| Interface Alerting (`apply.sh`, `netalert/`, `config/interfaces.<env>.yaml`, template, action) | **Unchanged from v1.0.2** — no file under `netalert/`, `config/environments/`, `config/interfaces.*.yaml`, `tests/` or `apply.sh` was modified. Template hash/`TOOL_VERSION` untouched, so a v1.0.2 installation reports no drift. |
| Network Health (new, optional, **disabled by default**) | `apply-health.sh`, `nethealth/`, `config/network-health.{production,lab}.yaml` (both empty), `docs/NETWORK-HEALTH.md`. OSPF neighbor, BGP peer, device unreachable, CPU, memory, SNMP stale. **UNTESTED.** |
| Review documents from the v1.0.2 production review | `docs/CLAUDE-FINAL-PRODUCTION-REVIEW.md`, `docs/OFFLINE-INSTALL-v1.0.2.md` (inherited from the base branch) |
| `VERSION` | 1.0.2 → 1.0.3 (not read by any code) |

## Backward compatibility

* With `config/network-health.<env>.yaml` empty (as shipped), and/or `apply-health.sh` never run, a v1.0.3 checkout behaves exactly like v1.0.2.
* Network Health uses its own templates, item keys (`nhealth.*`), macro namespace (`{$NHEALTH.*}`) and ownership marker, so the two tools cannot remove or modify each other's objects on a shared host (see `docs/NETWORK-HEALTH.md` §2).
* Notifications reuse the existing NETOPS-IaC e-mail action through the `netops_alert` event tag; the action itself is not modified.

## Validation status

| Check | Result |
|---|---|
| Python syntax (compile, Python 3.8 grammar) of new `nethealth/*.py`; YAML syntax of new config files; generated template JSON builds | done — syntax only, **not a test** |
| Unit tests, release gate, ShellCheck | **NOT RUN** (by instruction). No unit tests exist yet for `nethealth/`. |
| Zabbix import of the generated templates | **NOT RUN** |
| LAB / Production | **NOT RUN** — no access by instruction |

## Before tagging v1.0.3

1. Run `./scripts/release-gate.sh` (existing 182 tests must still pass; they do not cover Network Health).
2. Complete the LAB validation in `docs/NETWORK-HEALTH.md` §8 on at least one Cisco and one Huawei device.
3. Add offline unit tests for `nethealth/` (config parsing, plan, coexistence with `netalert` on a shared host).
4. Only then tag `v1.0.3` on the validated commit.

## Known limitations

OSPFv2 and IPv4 BGP only, default instance/VRF; no OSPFv3, IPv6 BGP or VRF peers; no firewall data-plane CPU;
no vendor-specific firewall template. Full list: `docs/NETWORK-HEALTH.md` §6.

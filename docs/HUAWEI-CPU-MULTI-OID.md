# Huawei CPU: multi-OID validated-value resolution

## Observed symptom

On some Huawei devices, the stock **Huawei VRP by SNMP** template's CPU item (which polls `HUAWEI-MIB::hwEntityCpuUsage` by default) returns `0` while the CLI reports a real, non-zero CPU figure. On other devices in the same fleet the same OID reports correctly. A different Huawei MIB object returns a non-zero figure on the affected devices.

**Do not hardcode one Huawei OID globally.** Different VRP releases and different hardware families expose CPU under different objects; some only expose it on the MPU, some per-slot, some via `HUAWEI-ENTITY-EXTENT-MIB`, some via `HUAWEI-DEVICE-MIB`, some via the standard `HOST-RESOURCES-MIB`.

## Resolution strategy (configuration-driven, no OID guessing)

### A. Make the stock template OID a macro, not a constant

Override the stock item's SNMP OID at the host-template level via a macro. Add this host-override to every Huawei host (and the Huawei host-group template):

| Macro | Default | Purpose |
|---|---|---|
| `{$HUAWEI.CPU.OID.PRIMARY}` | `1.3.6.1.4.1.2011.5.25.31.1.1.1.1.5` (`hwEntityCpuUsage`) | First-choice OID |
| `{$HUAWEI.CPU.OID.FALLBACK}` | `1.3.6.1.4.1.2011.6.3.4.1.3` (`hwCpuDevDuty`) | Fallback OID when PRIMARY returns 0 |
| `{$HUAWEI.CPU.ZERO_WINDOW_MIN}` | `10` | How many minutes of continuous 0 before we trust the fallback |

The CPU item on each Huawei host becomes a Zabbix **dependent item** whose master is a two-value SNMPv3 walk collecting *both* OIDs via a small bulk get. The item's preprocessing picks the non-zero value using a JavaScript step:

```javascript
// value is {"primary": N, "fallback": M}
var v = JSON.parse(value);
if (typeof v.primary === 'number' && v.primary > 0) return v.primary;
if (typeof v.fallback === 'number' && v.fallback > 0) return v.fallback;
return null; // propagate UNKNOWN, do NOT fabricate 0
```

A `null` result is important: it keeps the item in "no data / unknown" rather than reporting a fake zero.

### B. Per-model override table

Where known from onboarding, pin the OID explicitly on the host (overrides the macro default). Keep this table under version control, not in free-form comments:

See `templates/huawei/cpu-multi-oid/model-overrides.json`. Entries have:

```json
{ "model_regex": "S57\\d\\d", "primary_oid": "1.3.6.1.4.1.2011.6.3.4.1.3" }
```

Discovery sets the host macros on first poll; the override file is the authoritative mapping and is loaded by `scripts/apply-huawei-cpu-overrides.py`.

### C. Validation

For each Huawei host:

1. Collect `show cpu-usage` via SSH (one shot, read-only) and store in `evidence/huawei/<host>/cli-cpu.txt`.
2. Collect `snmpwalk -v3 … 1.3.6.1.4.1.2011.5.25.31.1.1.1.1.5` and `1.3.6.1.4.1.2011.6.3.4.1.3` and store under `evidence/huawei/<host>/snmp-cpu.txt`.
3. Choose the OID whose value is within 10 % of the CLI figure. Pin that OID. Add the result row to `templates/huawei/cpu-multi-oid/model-overrides.json`.

## Zabbix API side (bulk, no N+1)

`scripts/apply-huawei-cpu-overrides.py` uses `host.massupdate` to set the macros for all matching hosts in one call. Do NOT iterate one host at a time.

## Status in this build

The macro layout + the dependent-item + preprocessing recipe are documented. **The actual template edit is NOT applied in this build** because this build did not have Zabbix API credentials. Codex: apply the template update under the normal release gate.

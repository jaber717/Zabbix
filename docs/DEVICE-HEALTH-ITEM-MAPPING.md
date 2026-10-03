# Device Health — hardware column item mapping

## Observed symptom

Device Health's Power and Fan columns sometimes display values from unrelated numeric items on the host — for example an interface counter that happens to match a weak item-name regex.

## Root cause

A broad regex like `/power|psu/i` over `item.name` matches:

- the real `Power supply status`,
- but also `Interface <X> power level` on optical ports,
- and in some vendor templates even `Memory power configuration`.

## Fix (configuration-driven, no false matches)

The Device Health module (owned by Codex on `codex/device-health-v1`) should resolve hardware columns via a **vendor-aware, key-based** mapping instead of a free-form name regex. Candidate implementation:

1. Add `frontend/modules/DeviceHealth/config/hardware-item-matchers.json` with per-vendor rules:

```json
{
  "$schema_version": 1,
  "matchers": {
    "power": [
      {"vendor": "cisco", "key_regex": "^entPhySensorValue\\b.*(PSU|PowerSupply)"},
      {"vendor": "huawei", "key_regex": "hwEntityPowerStatus"},
      {"vendor": "fortinet", "key_regex": "fnSysPowerSupply"}
    ],
    "fan": [
      {"vendor": "cisco", "key_regex": "^(ciscoEnvMonFanStatus|entPhySensorValue\\b.*Fan)"},
      {"vendor": "huawei", "key_regex": "hwEntityFanState"}
    ],
    "temperature": [
      {"vendor": "cisco", "key_regex": "^entPhySensorValue\\b.*Temp"},
      {"vendor": "huawei", "key_regex": "hwEntityTemperature"}
    ]
  }
}
```

2. The collector matches on `item.key_` (SNMP OID key) **not** on `item.name`. Keys are stable; names are translated and vendor-templated.

3. If no match is found for a given column on a given host, the column shows `—` (Unknown) rather than a value from a different item. **Never fabricate a value.**

4. Vendor is derived from the host's attached template (`host.templates[].name` prefix `Cisco * / Huawei VRP * / FortiGate *`). If vendor is Unknown, the column is `—`.

## Status in this build

The matcher JSON above is proposed design, not a code change to the Device Health module (that module lives on `codex/device-health-v1`). Codex: apply this schema under the next Device Health release.

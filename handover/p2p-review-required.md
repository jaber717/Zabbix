# P2P review required

The selected list deliberately excludes anything that cannot be matched to both current device state and a Zabbix-discovered interface object.

## 1. SAIX-CORE GigabitEthernet0/0

- Description: `TO-SAIX-A-Gi0/0`
- Address: `172.16.2.1/30`; peer `172.16.2.2`
- Live state: up/up; iBGP peer established to SAIX-A.
- Assessment: verified P2P endpoint.
- Reason not selected: `SAIX-CORE` has no Zabbix host, template, SNMP interface, or `{#IFNAME}` discovery result.
- Required decision: onboard SAIX-CORE first, then verify the exact discovered `{#IFNAME}` before adding it.

## 2. SAIX-CORE GigabitEthernet0/1

- Description: `TO-SAIX-B-Gi0/0`
- Address: `172.16.2.5/30`; peer `172.16.2.6`
- Live state: up/up; iBGP peer established to SAIX-B.
- Assessment: verified P2P endpoint.
- Reason not selected: same missing Zabbix host/discovery as above.

## 3. PALO-LAB ethernet1/1

- Preserved topology/config evidence: `10.255.1.2/30`, peer SITE-A `10.255.1.1`.
- SITE-A live evidence: Gi0/3 up/up and BGP peer `10.255.1.2` established.
- Assessment: routed P2P link is strongly proven from the monitored side.
- Reason not selected: PALO-LAB is not a Zabbix host; its current CLI configuration/version was not re-read because no Palo Alto password is stored in the shared bundle.
- Required decision: obtain authorized interactive Palo access, onboard it with a validated template, and verify its exact Zabbix interface name.

## 4. PALO-LAB ethernet1/2

- Preserved topology/config evidence: `10.255.2.2/30`, peer SITE-B `10.255.2.1`.
- SITE-B live evidence: Gi0/3 up/up and BGP peer `10.255.2.2` established.
- Assessment: routed P2P link is strongly proven from the monitored side.
- Reason not selected: same missing Zabbix/Palo live verification as above.

## Explicitly rejected, not pending review

| Object | Evidence | Decision |
|---|---|---|
| INT-CORE Gi0/2 | `TO-INTERNET-ENDPOINT`, `198.18.1.1`, down/down, endpoint `/24` | Not a network-infrastructure P2P link; exclude |
| SITE-A Gi0/5 and Gi0/7 | OOB management role | Exclude |
| SITE-B Gi0/7 | OOB management role | Exclude |
| STC/MOBILY/INT-CORE/SAIX-A/SAIX-B Gi0/5 | OOB management role | Exclude |
| Loopback interfaces | Router IDs/test prefixes | Exclude |
| Admin-down interfaces | Unused/shutdown | Exclude |

## Operational prerequisite, not an interface-selection question

All seven current Zabbix SNMP interfaces report authentication failure. Fixing that mismatch is required before validating generated triggers or current traffic/error values. Do not treat the old discovered item identities as proof of current polling success, and do not change credentials silently.

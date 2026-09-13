# FortiGate onboarding

Zabbix 7.0.30 stock seed data contains **FortiGate by SNMP**. Live API structure
inspection found 53 direct items, nine discovery rules, 75 item prototypes, and
13 trigger prototypes. It covers availability, CPU, memory, interfaces,
traffic/errors/discards, sessions and hardware sensors, plus HA members, VPN
tunnels, VDOMs, wireless controllers, and SD-WAN health checks.

The observed stock template includes SD-WAN latency, jitter, loss, packet rate,
health state, filtering macros, and trigger prototypes. Thus SD-WAN structure is
implemented by the official pinned template; no custom module or unverified OID
was added. Actual FortiOS model/version support and live values still require a
real-device test.

## Procedure

1. On FortiGate, create a dedicated read-only SNMPv3 user restricted to the
   Zabbix poller address. Prefer authPriv with SHA-256 and AES-128.
2. In Zabbix, create the host and one SNMP interface on the management IP.
3. Enter SNMPv3 credentials in protected host macros/interface fields.
4. Attach `FortiGate by SNMP`.
5. Execute the relevant discoveries now or wait for normal discovery/polling.
6. Review VDOM, HA member, VPN tunnel, hardware sensor, and SD-WAN discovery
   filters before enabling alerting at production scale.

Useful stock controls include `{$IFCONTROL}`, `{$IF.UTIL.MAX}`,
`{$IF.ERRORS.WARN}`, interface match/not-match macros,
`{$HA.MEMBER.SN.MATCHES}`, `{$VDOM.NAME.MATCHES}`,
`{$VPN.*}` discovery behavior, and `{$SDWAN.HEALTH.*}` controls. Inspect the
actual macros exposed by the installed template version before overriding them.

If polling fails, test `sysUpTime.0` with a protected SNMP client invocation,
then verify the Fortinet MIB subtree, access profile, allowed source address,
engine ID, context, auth/privacy algorithms, and device firmware support.

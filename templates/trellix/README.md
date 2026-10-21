# Trellix (FireEye) SNMP templates for Zabbix 7.0

File to import: `zbx_templates_trellix_snmp.yaml` (6 templates, one import).

Built from the vendor MIB `FE-FIREEYE-MIB` (enterprise `1.3.6.1.4.1.25597`, revision 202105071327Z). Every OID, table column and
notification OID is generated from the MIB by `tools/gen_trellix.py`; nothing was typed by hand. The MIB itself is vendor-licensed and is not committed.

**Status: validated offline only.** It was not imported into a Zabbix server and not run against an appliance
(none was available). The validator checks structure and the MIB cross-references; it is not a Zabbix import test.

## Which template to link

| Template | Link to | Content |
|---|---|---|
| Trellix by SNMP | every appliance | ICMP/SNMP availability, MIB-II system, temperature, RAID + disk discovery, power, fans + fan discovery, image/content/licence state, licensed-feature discovery, guest images, AVC, submission totals |
| Trellix by SNMP traps | every appliance | all 55 notifications (`25597.*`), 24 triggers, automatic recovery for the 10 failure/recover pairs |
| Trellix CMS by SNMP | Central Management only | attached appliance counts, per-appliance disk/fan/PSU/RAID/temperature check results (discovery) |
| Trellix EMPS by SNMP | email appliances | email/URL/attachment statistics, queue snapshots, quarantine usage |
| Trellix WMPS by SNMP | network appliances | deployment check, MVX sizing, traffic/flow loss, detection stats and alert/threat/file-type counts by time span (discovery) |
| Trellix MAS by SNMP | malware-analysis appliances | analysed / malicious object, URL, file and live-mode counts |

The product-specific templates are linked **in addition to** `Trellix by SNMP`. Which objects an appliance model actually answers is not
stated by the MIB; an object an appliance does not implement will show as unsupported - unlink that template there.

## Host setup

* Polling: SNMP interface (v2c or v3; Counter64 objects need one of them), allow the Zabbix server/proxy IP in the appliance SNMP settings.
* Traps: Zabbix needs `snmptrapd` writing to the trapper file, `SNMPTrapperFile=` and `StartSNMPTrapper=1` in `zabbix_server.conf` (or the proxy),
  and the host's SNMP interface IP must equal the trap source address. Optional: put `TRELLIX-MIB.txt` in the net-snmp MIB path and
  `mibs +FE-FIREEYE-MIB`; the template matches both numeric OIDs and MIB names, so it works either way. Configure the trap sink on the appliance
  per the Trellix documentation (not covered here, not verified).

## Design decisions you should know about

* **Status strings are free text.** The MIB defines no values for `feSystemStatus`, `feRaidStatus`, `feFanStatus`, `fePhysicalDiskStatus` etc.
  They are stored as text and no trigger depends on them. Triggers use the `*IsHealthy` TruthValue objects (1 = true, 2 = false, from SNMPv2-TC) and traps.
* **Counters are not turned into rates.** The EMPS Counter64 objects are described as "the value for the past hour" (a window, not monotonic), and the
  WMPS/MAS counters do not say they are cumulative, so values are stored raw. If you confirm a MAS counter is cumulative, add `Change per second`.
  The WMPS sizing objects are typed Counter32 but are utilisation/status values; stored raw.
* **`feDeploymentCheckIsHealthy` is Unsigned32, not TruthValue**, values undefined: stored raw, no trigger.
* **Licence expiry days** (`feLicenseDaysUntilExpiration`) returns nothing for perpetual/inactive features, so that prototype is DISABLED by default.
* Submission totals are `(high<<32)+low` calculated items; high and low are read in separate requests, so a rollover between them can give one bad sample.
* Thresholds `{$TRELLIX.TEMP.WARN}` (70) and `{$TRELLIX.EMPS.QUARANTINE.WARN}` (80) are my assumptions, not vendor figures.
* Trap triggers without a recovery notification are manual-close. `feLogin/feLogout/feSyslogRotation/feTestTrap` raise an INFO problem; drop that trigger if too noisy.
* Not covered on purpose: `eventTable` and `lmsVersion/eventCount` (accessible-for-notify: only readable inside traps), AWS instance info, IPMI sub-tree,
  deprecated tables (`fePowerSupplyTable`, `feWMPSSubmission`), DateAndTime objects (binary format), the 32-bit H/L halves of Counter64 values.

## Tests performed (offline)

`tools/validate_trellix.py` (own OID resolver, independent of the generator's parser): UUID shape/uniqueness; every SNMP OID exists in the MIB, is
read-only and current, scalar `.0` vs table-column index correct; value type matches the MIB syntax; TruthValue items use the value map and are only compared with 1/2;
no rate on windowed counters; trigger/recovery key references; macros defined and used; every trigger-function and preprocessing parameter <= 255
characters (max here 238); all 55 notifications are matched by exactly one trigger in numeric, `FE-FIREEYE-MIB::name` and bare-name forms (165 checks),
lookalike OIDs (`1.3.6.1.4.1.125597...`) do not match; every pollable object is either used or on an explicit exclusion list.
13 deliberate mutations (wrong OID, notify-only OID, column used as scalar, rate on a window, 269-char parameter, missing regex boundary,
unknown key, TruthValue=3, undefined macro, duplicate UUID, missing value map, wrong trap OID, text type for numeric) were all caught.
A real bug found this way and fixed: the numeric trap regex also matched inside `125597.…`.

Regenerate: `python3 tools/gen_trellix.py out.yaml TRELLIX-MIB.txt && python3 tools/validate_trellix.py out.yaml TRELLIX-MIB.txt`

#!/usr/bin/env python3
"""Extract OIDs and enumerations from the Cisco-published MIB files (github.com/cisco/cisco-mibs, v2/) so the vendor definitions can be checked
against the MIB itself, offline.   usage: extract-cisco-mibs.py <dir with the .my files> <commit-sha> > cisco-mib-extract.json
Resolves OIDs by following the `::= { parent n }` chain from ciscoMgmt (1.3.6.1.4.1.9.9). Standard library only."""
import hashlib
import json
import os
import re
import sys

ROOTS = {"ciscoMgmt": "1.3.6.1.4.1.9.9"}
FILES = ("CISCO-ENVMON-MIB", "CISCO-ENTITY-FRU-CONTROL-MIB", "CISCO-ENTITY-SENSOR-MIB")
WANT = ("ciscoEnvMonFanStatusDescr", "ciscoEnvMonFanState", "ciscoEnvMonSupplyStatusDescr", "ciscoEnvMonSupplyState",
        "ciscoEnvMonTemperatureStatusDescr", "ciscoEnvMonTemperatureState", "ciscoEnvMonTemperatureStatusValue",
        "cefcFanTrayOperStatus", "cefcFRUPowerOperStatus", "entSensorStatus")
DEF = re.compile(r"^(\w+)[ \t]+(?:OBJECT-TYPE|MODULE-IDENTITY|OBJECT-IDENTITY)[ \t]*\r?$(.*?)::=\s*\{\s*([\w-]+)\s+(\d+)\s*\}", re.S | re.M)
OID = re.compile(r"^(\w+)\s+OBJECT IDENTIFIER\s*::=\s*\{\s*([\w-]+)\s+(\d+)\s*\}", re.M)
TC = re.compile(r"^(\w+)\s*::=\s*TEXTUAL-CONVENTION((?:(?!TEXTUAL-CONVENTION).)*?)SYNTAX\s+INTEGER\s*\{(.*?)\}", re.S | re.M)
ENUM = re.compile(r"(\w+)\s*\(\s*(\d+)\s*\)")


def main(d, commit):
    parent, body, tcs, mibs = {}, {}, {}, {}
    for name in FILES:
        raw = open(os.path.join(d, name + ".my"), "rb").read()
        text = raw.decode("utf-8", "replace")
        mibs[name] = {"url": "https://raw.githubusercontent.com/cisco/cisco-mibs/%s/v2/%s.my" % (commit, name), "sha256": hashlib.sha256(raw).hexdigest()}
        for m in DEF.finditer(text):
            parent[m.group(1)] = (m.group(3), int(m.group(4)))
            body[m.group(1)] = m.group(2)
        for m in OID.finditer(text):
            parent[m.group(1)] = (m.group(2), int(m.group(3)))
        for m in TC.finditer(text):
            tcs[m.group(1)] = dict((int(n), k) for k, n in ENUM.findall(m.group(3)))

    def resolve(n, seen=()):
        if n in ROOTS:
            return ROOTS[n]
        if n not in parent or n in seen:
            raise SystemExit("cannot resolve " + n)
        p, i = parent[n]
        return resolve(p, seen + (n,)) + "." + str(i)

    out = {"source": {"repository": "https://github.com/cisco/cisco-mibs", "commit": commit, "files": mibs}, "objects": {}}
    for w in WANT:
        b = body[w]
        syn = re.search(r"SYNTAX\s+(?:INTEGER\s*\{(.*?)\}|(\w+))", b, re.S)
        enum = None
        if syn:
            if syn.group(1):
                enum = dict((int(n), k) for k, n in ENUM.findall(syn.group(1)))
            elif syn.group(2) in tcs:
                enum = tcs[syn.group(2)]
        out["objects"][w] = {"oid": resolve(w), "enum": enum}
    print(json.dumps(out, indent=2, sort_keys=True))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

#!/usr/bin/env python3
"""Extract OIDs and enumerations for the Fortinet and Huawei definitions from MIB files, so the definitions can be checked against the MIB offline.
The MIB files are the vendors' own, as mirrored by the LibreNMS project (github.com/librenms/librenms, mibs/) at a pinned commit - a THIRD-PARTY MIRROR,
recorded as such: it is evidence of what the MIB text says, not a statement by the vendor about any device.

usage: extract-vendor-mibs.py <dir with the .mib files> <librenms-commit> > vendor-mib-extract.json
Resolves OIDs by following the `::= { parent n }` chain from `enterprises` (1.3.6.1.4.1). Standard library only."""
import hashlib
import json
import os
import re
import sys

ROOTS = {"enterprises": "1.3.6.1.4.1"}
FILES = {"FORTINET-CORE-MIB": "fortinet", "FORTINET-FORTIGATE-MIB": "fortinet", "HUAWEI-MIB": "huawei", "HUAWEI-ENTITY-EXTENT-MIB": "huawei"}
WANT = {"FORTINET-FORTIGATE-MIB": ("fgHwSensorEntName", "fgHwSensorEntAlarmStatus", "fgHaStatsSerial", "fgHaStatsSyncStatus", "fgHaSystemMode"),
        "HUAWEI-ENTITY-EXTENT-MIB": ("hwEntityFanState", "hwEntityTemperature")}
DEF = re.compile(r"^[ \t]*([A-Za-z]\w*)[ \t]+(?:OBJECT-TYPE|MODULE-IDENTITY|OBJECT-IDENTITY)\b(.*?)^[ \t]*::=\s*\{\s*([\w-]+)\s+(\d+)\s*\}", re.S | re.M)
OID = re.compile(r"^[ \t]*([A-Za-z]\w*)[ \t]+OBJECT IDENTIFIER\s*::=\s*\{\s*([\w-]+)\s+(\d+)\s*\}", re.M)
TC = re.compile(r"^[ \t]*(\w+)[ \t]*::=[ \t]*TEXTUAL-CONVENTION((?:(?!TEXTUAL-CONVENTION).)*?)SYNTAX\s+INTEGER\s*\{(.*?)\}", re.S | re.M)
ENUM = re.compile(r"(\w+)\s*\(\s*(\d+)\s*\)")


def main(d, commit):
    parent, body, tcs, mibs = {}, {}, {}, {}
    objname_by_mib = {}
    for name, vendor in sorted(FILES.items()):
        raw = open(os.path.join(d, name + ".mib"), "rb").read()
        text = raw.decode("utf-8", "replace")
        mibs[name] = {"url": "https://raw.githubusercontent.com/librenms/librenms/%s/mibs/%s/%s" % (commit, vendor, name), "sha256": hashlib.sha256(raw).hexdigest()}
        for m in DEF.finditer(text):
            if m.group(1) not in parent:
                parent[m.group(1)] = (m.group(3), int(m.group(4)))
                body[m.group(1)] = m.group(2)
                objname_by_mib[m.group(1)] = name
        for m in OID.finditer(text):
            parent.setdefault(m.group(1), (m.group(2), int(m.group(3))))
        for m in TC.finditer(text):
            tcs[m.group(1)] = dict((int(n), k) for k, n in ENUM.findall(m.group(3)))

    def resolve(n, seen=()):
        if n in ROOTS:
            return ROOTS[n]
        if n not in parent or n in seen:
            raise SystemExit("cannot resolve " + n)
        p, i = parent[n]
        return resolve(p, seen + (n,)) + "." + str(i)

    out = {"source": {"repository": "https://github.com/librenms/librenms", "commit": commit, "note": "third-party mirror of the vendor MIB files", "files": mibs}, "objects": {}}
    for mib, names in WANT.items():
        for w in names:
            if objname_by_mib.get(w) != mib:
                raise SystemExit("%s was not found in %s" % (w, mib))
            b = body[w]
            syn = re.search(r"SYNTAX\s+(?:INTEGER\s*\{(.*?)\}|(\w+))", b, re.S)
            enum = None
            if syn:
                if syn.group(1):
                    enum = dict((int(n), k) for k, n in ENUM.findall(syn.group(1)))
                elif syn.group(2) in tcs:
                    enum = tcs[syn.group(2)]
            out["objects"][w] = {"mib": mib, "oid": resolve(w), "enum": enum}
    print(json.dumps(out, indent=2, sort_keys=True))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

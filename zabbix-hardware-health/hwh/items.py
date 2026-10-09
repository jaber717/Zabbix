"""Item evidence: what an item REALLY is (raw SNMP walk input vs concrete sensor), its value, timestamp, units, OID, preprocessing and value map.

Keyword hints (`classify`) only nominate CANDIDATES for a human to review. They never make a sensor count as monitored."""
import datetime
import re

ITEM_FIELDS = ["itemid", "name", "key_", "type", "value_type", "units", "snmp_oid", "lastvalue", "lastclock", "delay",
               "status", "state", "error", "flags", "master_itemid", "valuemapid"]
ITEM_SELECTS = {"selectValueMap": ["name", "mappings"], "selectPreprocessing": ["type", "params"], "selectTags": ["tag", "value"]}
MAX_TEXT = 200

RAW_KEY_RE = re.compile(r"(?:^|[.\[_-])walk(?:$|[.\]\[_-])", re.I)
IDENTITY_KEY_RE = re.compile(r"system\.(?:descr|objectid|hw\.model|sw\.os|sw\.name)|sysdescr|sysobjectid|\.model(?:\[|$)", re.I)

HINTS = {
    "fan": re.compile(r"\b(?:fans?|blowers?|fantray|fan.tray)\b", re.I),
    "power": re.compile(r"\b(?:psu|ps[12]|power[\s_-]*suppl(?:y|ies)|power[\s_-]*modules?|pwr)\b", re.I),
    "temperature": re.compile(r"\b(?:temperatures?|thermal|overheat|thermometer)\b", re.I),
    "hw_redundancy": re.compile(r"\b(?:redundan(?:t|cy)|lost[\s_-]*redundancy)\b", re.I),
    "ha": re.compile(r"\b(?:ha|high[\s_-]*availability|cluster|ha[\s_-]*(?:member|peer|state|mode|sync|priority|group))\b", re.I),
}


def classify(text):
    """Candidate category hints from NAME/KEY TEXT ONLY. Not an assertion of anything.
    HA (cluster state) and hardware redundancy (fan/PSU redundancy) are different things and never share a hint."""
    text = str(text or "")
    m = [k for k in HINTS if HINTS[k].search(text)]
    if "hw_redundancy" in m and "ha" in m:
        m.remove("hw_redundancy" if not (HINTS["fan"].search(text) or HINTS["power"].search(text)) else "ha")
    if "hw_redundancy" in m:
        m = [k for k in m if k not in ("fan", "power", "ha")]            # the redundancy STATE, not the fan/PSU itself
    if "fan" in m:
        m = [k for k in m if k != "power"]                                # a PSU fan is a fan sensor
    return m


def master_ids(items):
    return set(str(i["master_itemid"]) for i in items if str(i.get("master_itemid") or "0") not in ("", "0"))


def raw_reason(item, masters):
    """Why this item is a raw SNMP walk / discovery input rather than one physical sensor (None = concrete)."""
    oid = str(item.get("snmp_oid") or "")
    if oid.lower().startswith("walk["):
        return "snmp walk (oid %s)" % oid[:60]
    if RAW_KEY_RE.search(str(item.get("key_") or "")):
        return "walk key"
    if str(item.get("itemid")) in masters:
        return "master item of dependent items"
    try:
        if int(item.get("flags") or 0) & 1:
            return "discovery rule"
    except (TypeError, ValueError):
        pass
    return None


def _trunc(v):
    s = "" if v is None else str(v)
    return s if len(s) <= MAX_TEXT else s[:MAX_TEXT] + "..."


def evidence(item, now, masters):
    clock = int(item.get("lastclock") or 0)
    vm = item.get("valuemap") or {}
    if isinstance(vm, list):                     # an empty value map comes back as []
        vm = {}
    return {
        "itemid": str(item.get("itemid")), "name": _trunc(item.get("name")), "key": _trunc(item.get("key_")),
        "item_type": str(item.get("type")), "value_type": str(item.get("value_type")), "snmp_oid": _trunc(item.get("snmp_oid")),
        "units": _trunc(item.get("units")), "delay": str(item.get("delay") or ""),
        "lastvalue": _trunc(item.get("lastvalue")), "lastclock": clock,
        "lastclock_utc": (None if not clock else datetime.datetime.fromtimestamp(clock, datetime.timezone.utc).isoformat()),
        "age_seconds": (None if not clock else max(0, int(now) - clock)),
        "enabled": str(item.get("status")) == "0", "supported": str(item.get("state")) == "0", "error": _trunc(item.get("error")),
        "master_itemid": str(item.get("master_itemid") or "0"),
        "valuemap": {"name": vm.get("name", ""), "mappings": [{"value": m.get("value"), "newvalue": m.get("newvalue")} for m in vm.get("mappings", [])]} if vm else None,
        "preprocessing": [{"type": str(p.get("type")), "params": _trunc(p.get("params"))} for p in (item.get("preprocessing") or [])],
        "tags": sorted([t.get("tag", ""), t.get("value", "")] for t in (item.get("tags") or [])),
        "raw_input": raw_reason(item, masters),
    }


def fetch_items(api, hostid):
    params = {"hostids": [hostid], "output": ITEM_FIELDS}
    params.update(ITEM_SELECTS)
    return api.call("item.get", params)

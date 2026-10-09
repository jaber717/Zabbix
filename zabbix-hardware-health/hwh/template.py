"""Generate the Zabbix 7.0 template 'NETOPS-HW <definition id>' from a vendor definition (pure; nothing is sent anywhere).

Shape follows the official Zabbix 7.0 vendor templates (walk master item -> dependent LLD rule -> dependent item prototypes with nested trigger
prototypes), which are known to import. Every alarm trigger carries the dedicated routing tags (netops_hardware=1, hardware_component,
hardware_vendor, hardware_model, hardware_site, hardware_slot) and NEVER netops_alert. False-positive protection: a problem needs
`confirm_samples` consecutive alarm samples; recovery needs `recover_samples` consecutive normal samples; a missing / unsupported reading is a
SEPARATE `sensor_stale` trigger, never a hardware alarm.
"""
import hashlib
import json

from . import expr
from . import vendordefs as VD
from .policy import COMPONENT_TAG

TEMPLATE_PREFIX = "NETOPS-HW "
MARKER = "managed_by=netops-hardware-health"
TOOL_VERSION = "1.0"
TEMPLATE_GROUP = "Templates/Network devices"
PRIORITY = {"information": "INFO", "warning": "WARNING", "average": "AVERAGE", "high": "HIGH", "disaster": "DISASTER"}
ROUTING = "netops_hardware"
MACROS = [
    ("{$NETOPS.HW.MODEL}", "", "Exact device model, set on the HOST (event tag hardware_model and message text)."),
    ("{$NETOPS.HW.SITE}", "", "Site label, set on the HOST (event tag hardware_site)."),
    ("{$NETOPS.HW.STALE}", "15m", "No data for this long raises the sensor_stale monitoring-quality trigger (never a hardware alarm)."),
    ("{$NETOPS.HW.POLL}", "1m", "Poll interval of the sensor walk."),
]
API_MACROS = [
    ("{$NETOPS.HW.API.URL}", "", "PAN-OS XML API endpoint <scheme>://<host>[:port]/api, set on the HOST."),
    ("{$NETOPS.HW.API.USER}", "", "Read-only API user, set on the HOST."),
    ("{$NETOPS.HW.API.PASSWORD}", "", "Password of that user, set on the HOST as a SECRET macro. Never stored in this repository."),
    ("{$NETOPS.HW.API.TIMEOUT}", "15s", "API timeout."),
    ("{$NETOPS.HW.API.HTTP_PROXY}", "", "HTTP proxy for the API items (set if needed; empty = no proxy)."),
]


def template_name(defn):
    return TEMPLATE_PREFIX + defn["id"]


def uuid_for(seed):
    h = list(hashlib.md5(("netops-hw:" + seed).encode("utf-8")).hexdigest())
    h[12] = "4"
    h[16] = "89ab"[int(h[16], 16) % 4]
    return "".join(h)


def valuemap_name(sem_id):
    return TEMPLATE_PREFIX + sem_id


def _tags_for(defn, sn, component_tag, slot):
    return [{"tag": ROUTING, "value": "1"}, {"tag": "hardware_component", "value": component_tag}, {"tag": "hardware_vendor", "value": defn["vendor"]},
            {"tag": "hardware_model", "value": "{$NETOPS.HW.MODEL}"}, {"tag": "hardware_site", "value": "{$NETOPS.HW.SITE}"},
            {"tag": "hardware_slot", "value": slot}]


def _trigger_protos(defn, sn, key, slot):
    out = []
    sem = defn["semantics"][sn["value"]["semantics"]]
    normal = VD.raw_values_for(defn, sn["value"]["semantics"], ["normal"])
    tpl = template_name(defn)
    for t in sn.get("triggers") or []:
        raws = VD.raw_values_for(defn, sn["value"]["semantics"], t["states"])
        problem = expr.problem_expression(tpl, key, raws, t["confirm_samples"])
        rec = expr.recovery_expression(tpl, key, normal, t["recover_samples"])
        out.append({
            "uuid": uuid_for("trigger:%s:%s:%s" % (defn["id"], sn["id"], t["id"])),
            "expression": problem, "recovery_mode": "RECOVERY_EXPRESSION", "recovery_expression": rec,
            "name": "%s: %s: %s" % (defn["id"], t["title"], slot),
            "event_name": "%s: %s on %s (state: {ITEM.VALUE})" % (defn["id"], t["title"], slot),
            "opdata": "Current state: {ITEM.LASTVALUE}",
            "priority": PRIORITY[t["severity"]],
            "description": "%s. Raised after %d consecutive alarm samples; cleared after %d consecutive normal samples. Source: %s. %s" % (
                t["title"], t["confirm_samples"], t["recover_samples"], sem["object"], "Documentation-derived classification; not device-verified."),
            "tags": _tags_for(defn, sn, COMPONENT_TAG[sn["category"]], slot)})
    return out


def _preproc_walk_value(oid_expr, heartbeat=True):
    """Status items that carry triggers must store EVERY sample: the confirm / recover logic counts last(#n) samples, and discarding unchanged
    values would silently turn \"2 samples\" into \"2 heartbeats\". Only informational readings may discard unchanged values."""
    pre = [{"type": "SNMP_WALK_VALUE", "parameters": [oid_expr, "0"]}]
    if heartbeat:
        pre.append({"type": "DISCARD_UNCHANGED_HEARTBEAT", "parameters": ["3m"]})
    return pre


def _snmp_sensor(defn, sn):
    tpl = template_name(defn)
    sid = sn["id"]
    walk_key = "netops.hw.%s.walk" % sid
    disc_key = "netops.hw.%s.discovery" % sid
    item_key = "netops.hw.%s[{#SNMPINDEX}]" % sid
    v = sn["value"]
    master = {
        "uuid": uuid_for("walk:%s:%s" % (defn["id"], sid)), "name": "%s: SNMP walk %s" % (defn["id"], sn["title"]), "type": "SNMP_AGENT",
        "snmp_oid": "walk[%s,%s]" % (sn["table"]["name_oid"], v["oid"]), "key": walk_key, "delay": "{$NETOPS.HW.POLL}",
        "history": "1h", "value_type": "TEXT", "trends": "0",
        "description": "Raw SNMP walk feeding discovery and the dependent items. A raw input, not a sensor. Source object: %s." % v["object"],
        "tags": [{"tag": "component", "value": "raw"}],
        "triggers": [{
            "uuid": uuid_for("stale:%s:%s" % (defn["id"], sid)), "expression": expr.stale_expression(tpl, walk_key, "{$NETOPS.HW.STALE}"),
            "name": "%s: no hardware data for %s" % (defn["id"], sn["title"]), "priority": "WARNING",
            "description": "No SNMP data for {$NETOPS.HW.STALE}: device unreachable, SNMP unsupported or stale. This is a MONITORING-QUALITY event and NOT a fan/PSU/temperature failure.",
            "tags": _tags_for(defn, sn, "sensor_stale", sid)}]}
    if sn["scope"] == "reading":
        units = v.get("units", "")
        proto = {"uuid": uuid_for("item:%s:%s" % (defn["id"], sid)), "name": "{#HW.NAME}: %s" % sn["title"], "type": "DEPENDENT", "key": item_key,
                 "delay": "0", "value_type": "FLOAT", "units": units, "history": "7d", "trends": "30d",
                 "description": "MIB object %s. %s" % (v["object"], sn.get("note", "")),
                 "preprocessing": _preproc_walk_value("%s.{#SNMPINDEX}" % v["oid"]), "master_item": {"key": walk_key},
                 "tags": [{"tag": "component", "value": COMPONENT_TAG[sn["category"]]}, {"tag": "sensor", "value": "{#HW.NAME}"}]}
    else:
        sem = defn["semantics"][v["semantics"]]
        proto = {"uuid": uuid_for("item:%s:%s" % (defn["id"], sid)), "name": "{#HW.NAME}: %s" % sn["title"], "type": "DEPENDENT", "key": item_key,
                 "delay": "0", "value_type": "UNSIGNED", "history": "7d", "trends": "0",
                 "description": "MIB object %s. %s" % (sem["object"], sn.get("note", "")),
                 "valuemap": {"name": valuemap_name(v["semantics"])},
                 "preprocessing": _preproc_walk_value("%s.{#SNMPINDEX}" % v["oid"], heartbeat=False), "master_item": {"key": walk_key},
                 "tags": [{"tag": "component", "value": COMPONENT_TAG[sn["category"]]}, {"tag": "sensor", "value": "{#HW.NAME}"}],
                 "trigger_prototypes": _trigger_protos(defn, sn, item_key, "{#HW.NAME}")}
    rule = {"uuid": uuid_for("lld:%s:%s" % (defn["id"], sid)), "name": "%s: %s discovery" % (defn["id"], sn["title"]), "type": "DEPENDENT",
            "key": disc_key, "delay": "0",
            "filter": {"evaltype": "AND_OR", "conditions": [{"macro": "{#HW.VAL}", "value": ".+", "operator": "MATCHES_REGEX", "formulaid": "A"}]},
            "description": "Rows are selected by the PRESENCE of the value column, so only rows that carry this sensor are discovered.",
            "item_prototypes": [proto], "master_item": {"key": walk_key},
            "preprocessing": [{"type": "SNMP_WALK_TO_JSON", "parameters": ["{#HW.NAME}", sn["table"]["name_oid"], "0", "{#HW.VAL}", v["oid"], "0"],
                               "error_handler": "DISCARD_VALUE"}, {"type": "DISCARD_UNCHANGED_HEARTBEAT", "parameters": ["1h"]}]}
    return master, rule


def _api_sensor(defn, sn):
    tpl = template_name(defn)
    sid = sn["id"]
    a = sn["api"]
    gate = a.get("gate")
    get_key = "netops.hw.%s.get" % sid
    key = ("netops.hw.%s[state{#HW.SINGLETON}]" if gate else "netops.hw.%s") % sid
    master = {
        "uuid": uuid_for("get:%s:%s" % (defn["id"], sid)), "name": "%s: API %s" % (defn["id"], sn["title"]), "type": "HTTP_AGENT", "key": get_key,
        "delay": "{$NETOPS.HW.POLL}", "history": "1h", "value_type": "TEXT", "trends": "0", "authtype": "BASIC",
        "username": "{$NETOPS.HW.API.USER}", "password": "{$NETOPS.HW.API.PASSWORD}", "timeout": "{$NETOPS.HW.API.TIMEOUT}", "status_codes": "", "http_proxy": "{$NETOPS.HW.API.HTTP_PROXY}",
        "url": "{$NETOPS.HW.API.URL}", "query_fields": [{"name": k, "value": v} for k, v in sorted(a["query"].items())] + [{"name": "cmd", "value": a["command"]}],
        "description": "Raw API response (read-only operational command). A raw input, not a sensor.",
        "preprocessing": [{"type": "XML_TO_JSON", "parameters": [""]}], "tags": [{"tag": "component", "value": "raw"}],
        "triggers": [{
            "uuid": uuid_for("stale:%s:%s" % (defn["id"], sid)), "expression": expr.stale_expression(tpl, get_key, "{$NETOPS.HW.STALE}"),
            "name": "%s: no hardware data for %s" % (defn["id"], sn["title"]), "priority": "WARNING",
            "description": "No API data for {$NETOPS.HW.STALE}: device unreachable, credentials rejected or API unsupported. MONITORING-QUALITY event, NOT a hardware failure.",
            "tags": _tags_for(defn, sn, "sensor_stale", sid)}]}
    pre = [{"type": "JSONPATH", "parameters": [a["json_path"]]}]
    if "index_map" in a:
        pre.append({"type": "JAVASCRIPT", "parameters": ["const idx = %s.indexOf(value);\nreturn idx !== -1 ? idx : %d;" % (
            json.dumps(a["index_map"]), a["unknown_index"])]})
    if sn["scope"] == "reading":
        pre.append({"type": "DISCARD_UNCHANGED_HEARTBEAT", "parameters": ["3m"]})
    v = sn["value"]
    dep = {"uuid": uuid_for("item:%s:%s" % (defn["id"], sid)), "name": "%s" % sn["title"], "type": "DEPENDENT", "key": key, "delay": "0",
           "value_type": "FLOAT" if v["type"] == "float" else "UNSIGNED", "history": "7d", "trends": "30d" if v["type"] == "float" else "0",
           "description": "API path %s. %s" % (a["json_path"], sn.get("note", "")), "preprocessing": pre, "master_item": {"key": get_key},
           "tags": [{"tag": "component", "value": COMPONENT_TAG[sn["category"]]}]}
    if v.get("units"):
        dep["units"] = v["units"]
    if sn["scope"] != "reading":
        dep["valuemap"] = {"name": valuemap_name(v["semantics"])}
        trig = _trigger_protos(defn, sn, key, sid)
        if gate:
            dep["trigger_prototypes"] = trig
        else:
            dep["triggers"] = trig
            for t in trig:
                t.pop("event_name", None)
    if not gate:
        return master, dep, None
    # the item exists only while the gate holds (e.g. HA enabled): a discovery singleton, as in the reference template, so a device without the
    # feature produces NO unsupported item. ES5-only JavaScript (Zabbix uses Duktape): no for-of, no arrow functions.
    js = "\n".join([
        "var d = JSON.parse(value), v = d, p = %s, i;" % json.dumps(gate["path"]),
        "for (i = 0; i < p.length; i++) {",
        "    if (v === null || typeof v !== 'object' || !(p[i] in v)) { return JSON.stringify([]); }",
        "    v = v[p[i]];",
        "}",
        "return JSON.stringify(v === %s ? [{'{#HW.SINGLETON}': ''}] : []);" % json.dumps(gate["equals"])])
    rule = {"uuid": uuid_for("lld:%s:%s" % (defn["id"], sid)), "name": "%s: %s discovery" % (defn["id"], sn["title"]), "type": "DEPENDENT", "key": "netops.hw.%s.discovery" % sid,
            "delay": "0", "description": "Creates the item only when %s = %s in the API response; otherwise nothing is created." % (".".join(gate["path"]), gate["equals"]),
            "item_prototypes": [dep], "master_item": {"key": get_key},
            "preprocessing": [{"type": "JAVASCRIPT", "parameters": [js]}, {"type": "DISCARD_UNCHANGED_HEARTBEAT", "parameters": ["1h"]}]}
    return master, None, rule


def build_payload(defn, tpl_hash=""):
    if defn["kind"] == "snmp":
        macros = MACROS
    else:
        macros = MACROS + API_MACROS
    items, rules = [], []
    for sn in defn.get("sensors") or []:
        if defn["kind"] == "snmp":
            master, rule = _snmp_sensor(defn, sn)
            items.append(master)
            rules.append(rule)
        else:
            master, dep, rule = _api_sensor(defn, sn)
            items.append(master)
            if dep is not None:
                items.append(dep)
            if rule is not None:
                rules.append(rule)
    used = sorted({sn["value"]["semantics"] for sn in defn.get("sensors") or [] if sn["scope"] != "reading"})
    valuemaps = [{"uuid": uuid_for("valuemap:" + s), "name": valuemap_name(s),
                  "mappings": [{"value": str(k), "newvalue": v["meaning"]} for k, v in sorted(defn["semantics"][s]["states"].items(), key=lambda kv: int(kv[0]))]}
                 for s in used]
    tmpl = {"uuid": uuid_for("template:" + defn["id"]), "template": template_name(defn), "name": template_name(defn),
            "description": "%s version=%s definition=%s hash=%s. Generated; do not edit in the GUI. Documentation-derived; not device-verified." % (
                MARKER, TOOL_VERSION, defn["id"], tpl_hash),
            "groups": [{"name": TEMPLATE_GROUP}], "items": items, "discovery_rules": rules, "valuemaps": valuemaps,
            "macros": [dict({"macro": m, "value": val, "description": d}, **({"type": "SECRET_TEXT"} if "PASSWORD" in m else {})) for m, val, d in macros]}
    if not rules:
        tmpl.pop("discovery_rules")
    return {"zabbix_export": {"version": "7.0", "template_groups": [{"uuid": uuid_for("group:" + TEMPLATE_GROUP), "name": TEMPLATE_GROUP}], "templates": [tmpl]}}


def content_hash(defn):
    blob = json.dumps(build_payload(defn, ""), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def build(defn):
    """Final import document, with the content hash embedded in the template description (the drift / ownership marker)."""
    return build_payload(defn, content_hash(defn))


IMPORT_RULES = {
    "template_groups": {"createMissing": True, "updateExisting": False},
    "templates": {"createMissing": True, "updateExisting": True},
    "valueMaps": {"createMissing": True, "updateExisting": True, "deleteMissing": False},
    "discoveryRules": {"createMissing": True, "updateExisting": True, "deleteMissing": True},
    "items": {"createMissing": True, "updateExisting": True, "deleteMissing": True},
    "triggers": {"createMissing": True, "updateExisting": True, "deleteMissing": True},
}

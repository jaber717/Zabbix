"""Offline structural validation of a generated template document: what Zabbix would reject or what would break routing, found before import."""
import re

from . import expr
from .api import AuditError

ALLOWED_PRIORITY = {"NOT_CLASSIFIED", "INFO", "WARNING", "AVERAGE", "HIGH", "DISASTER"}
REQUIRED_TAGS = {"netops_hardware", "hardware_component", "hardware_vendor", "hardware_model", "hardware_site", "hardware_slot"}
COMPONENTS = {"fan", "power", "temperature", "redundancy", "ha", "sensor", "sensor_stale"}
UUID_RE = re.compile(r"^[0-9a-f]{32}$")


def check(doc):
    """-> list of problem strings (empty = structurally sound)."""
    problems = []
    try:
        ex = doc["zabbix_export"]
        tmpl = ex["templates"][0]
    except (KeyError, IndexError, TypeError):
        return ["not a zabbix_export document"]
    if ex.get("version") != "7.0":
        problems.append("export version must be 7.0")
    name = tmpl["template"]
    uuids, keys = [], {}

    def uid(o, what):
        u = o.get("uuid", "")
        if not UUID_RE.match(u) or u[12] != "4":
            problems.append("%s: bad uuid" % what)
        uuids.append(u)

    uid(tmpl, "template")
    for vm in tmpl.get("valuemaps", []):
        uid(vm, "valuemap " + vm["name"])
    master_keys = set()
    items = list(tmpl.get("items", []))
    for it in items:
        uid(it, "item " + it["key"])
        keys[it["key"]] = it
        master_keys.add(it["key"])
    rules = tmpl.get("discovery_rules", [])
    for r in rules:
        uid(r, "rule " + r["key"])
        master_keys.add(r["key"])
        for ip in r.get("item_prototypes", []):
            uid(ip, "prototype " + ip["key"])
            keys[ip["key"]] = ip
    vm_names = {v["name"] for v in tmpl.get("valuemaps", [])}

    def check_trigger(t, what, allow_hw):
        uid(t, what)
        if t.get("priority") not in ALLOWED_PRIORITY:
            problems.append("%s: bad priority" % what)
        tags = {x["tag"]: x["value"] for x in t.get("tags", [])}
        if "netops_alert" in tags:
            problems.append("%s: carries netops_alert (would cross into Interface Alerting)" % what)
        if not REQUIRED_TAGS <= set(tags) or tags.get("netops_hardware") != "1":
            problems.append("%s: missing routing tags %s" % (what, sorted(REQUIRED_TAGS - set(tags))))
        if tags.get("hardware_component") not in COMPONENTS:
            problems.append("%s: hardware_component %r not in the contract" % (what, tags.get("hardware_component")))
        for field in ("expression", "recovery_expression"):
            if t.get(field):
                try:
                    tree = expr.parse(t[field])
                except AuditError as e:
                    problems.append("%s: %s unparsable: %s" % (what, field, e))
                    continue
                for tp, k in expr.references(tree):
                    base = k
                    if tp != name:
                        problems.append("%s: expression references template %s" % (what, tp))
                    elif base not in keys and base not in master_keys:
                        problems.append("%s: expression references unknown key %s" % (what, base))
        if t.get("recovery_mode") == "RECOVERY_EXPRESSION" and not t.get("recovery_expression"):
            problems.append("%s: recovery_mode without expression" % what)
        if tags.get("hardware_component") != "sensor_stale" and t.get("recovery_mode") != "RECOVERY_EXPRESSION":
            problems.append("%s: alarm trigger has no recovery expression (flapping protection missing)" % what)

    for it in items:
        for t in it.get("triggers", []):
            check_trigger(t, "trigger " + t["name"], True)
    for r in rules:
        mk = r["master_item"]["key"]
        if mk not in keys:
            problems.append("rule %s: master item %s missing" % (r["key"], mk))
        for ip in r.get("item_prototypes", []):
            if ip["master_item"]["key"] not in keys:
                problems.append("prototype %s: master item missing" % ip["key"])
            vmref = (ip.get("valuemap") or {}).get("name")
            if vmref and vmref not in vm_names:
                problems.append("prototype %s: valuemap %s not defined" % (ip["key"], vmref))
            for t in ip.get("trigger_prototypes", []):
                check_trigger(t, "trigger prototype " + t["name"], True)
    for it in items:
        mk = (it.get("master_item") or {}).get("key")
        if mk and mk not in keys:
            problems.append("item %s: master item %s missing" % (it["key"], mk))
        vmref = (it.get("valuemap") or {}).get("name")
        if vmref and vmref not in vm_names:
            problems.append("item %s: valuemap %s not defined" % (it["key"], vmref))
    if len(set(uuids)) != len(uuids):
        problems.append("duplicate uuid in the document")
    for m in tmpl.get("macros", []):
        if "PASSWORD" in m["macro"] and (m.get("type") != "SECRET_TEXT" or m.get("value")):
            problems.append("password macro must be SECRET_TEXT with no value")
    if "managed_by=netops-hardware-health" not in tmpl.get("description", ""):
        problems.append("ownership marker missing from the template description")
    return problems

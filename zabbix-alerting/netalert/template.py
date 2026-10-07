"""The generated, fully owned Zabbix template 'NETOPS Interface Alerting'.

The template is static: it never contains an interface name. Which interfaces
alert, and with which thresholds, comes only from host user macros that the
planner derives from interfaces.yaml. One LLD rule is filtered with a regex macro
so only selected interfaces get items and triggers; the stock templates keep
monitoring every other interface untouched.

Imported with configuration.import (supported API, no SQL). All uuids are
derived deterministically so re-imports update in place.
"""
import copy
import hashlib
import json
import re

TOOL_VERSION = "1.0"
MARKER = "managed_by=zabbix-alerting-as-code"
TEMPLATE_NAME = "NETOPS Interface Alerting"
TEMPLATE_GROUP = "Templates/Network devices"
MACRO_PREFIX = "{$NETOPS."
TAG_ALERT = "netops_alert"

SEVERITY_VARIANTS = (("warning", 2, "WARNING"), ("average", 3, "AVERAGE"),
                     ("high", 4, "HIGH"), ("disaster", 5, "DISASTER"))

# template-level defaults: what an interface gets when a context macro is absent
TEMPLATE_MACROS = [
    ("{$NETOPS.IF.MATCH}", "^$", "Regex of selected interface names. Generated from interfaces.yaml."),
    ("{$NETOPS.SITE}", "", "Site label. Generated."),
    ("{$NETOPS.DESCR}", "", "Interface description (context = interface). Generated."),
    ("{$NETOPS.ROLE}", "", "Interface role (context = interface). Generated."),
    ("{$NETOPS.SEV}", "4", "Severity 2..5 (context = interface). Generated."),
    ("{$NETOPS.LINK}", "1", "Link down/up alert on (1) or off (0)."),
    ("{$NETOPS.LINKID}", "", "Identifier shared by both ends of one physical link (event tag link_id)."),
    ("{$NETOPS.POLL}", "10s", "Poll interval for link and traffic items of selected interfaces."),
    ("{$NETOPS.POLL.SLOW}", "60s", "Poll interval for error/discard/speed items."),
    ("{$NETOPS.UTIL.ON}", "0", "Utilization alert on (1) or off (0)."),
    ("{$NETOPS.UTIL.MAX}", "70", "Utilization problem threshold, percent of link speed (last sample)."),
    ("{$NETOPS.UTIL.RECOVER}", "65", "Utilization recovery threshold, percent (hysteresis)."),
    ("{$NETOPS.ERR.ON}", "1", "Error-rate alert on (1) or off (0)."),
    ("{$NETOPS.ERR.RATE}", "1", "Errors per second that raise the problem."),
    ("{$NETOPS.ERR.RECOVER}", "0", "Errors per second at or below which the problem recovers."),
    ("{$NETOPS.DISC.ON}", "1", "Discard-rate alert on (1) or off (0)."),
    ("{$NETOPS.DISC.RATE}", "1", "Discards per second that raise the problem."),
    ("{$NETOPS.DISC.RECOVER}", "0", "Discards per second at or below which the problem recovers."),
    ("{$NETOPS.FLAP.ON}", "1", "Flapping alert on (1) or off (0)."),
    ("{$NETOPS.FLAP.COUNT}", "3", "Oper-status changes inside the window that count as flapping."),
    ("{$NETOPS.FLAP.WINDOW}", "10m", "Flapping detection window."),
    ("{$NETOPS.SPEED.EXPECTED}", "0", "Expected speed in bps (0 = unset). Also overrides the capacity used for utilization."),
]


def uuid_for(seed):
    h = list(hashlib.md5(("netops-iac:" + seed).encode("utf-8")).hexdigest())
    h[12] = "4"
    h[16] = "89ab"[int(h[16], 16) % 4]
    return "".join(h)


def ctx(name):
    return '{$NETOPS.%s:"{#IFNAME}"}' % name


def _tags(extra=None):
    tags = [{"tag": "component", "value": "network"}, {"tag": "interface", "value": "{#IFNAME}"}]
    return tags + (extra or [])


def _item(name, key, oid, delay, value_type, units, pre=None, item_type="SNMP_AGENT", master=None,
          tags=None):
    it = {
        "uuid": uuid_for("item:" + key),
        "name": name,
        "type": item_type,
        "key": key,
        "delay": delay,
        "history": "7d",
        "trends": "0" if value_type == "UNSIGNED" else "30d",
        "value_type": value_type,
        "units": units,
        "tags": tags or _tags(),
    }
    if item_type == "SNMP_AGENT":
        it["snmp_oid"] = oid
    else:
        it.pop("delay")
        it["master_item"] = {"key": master}
    if pre:
        it["preprocessing"] = pre
    return it


def _rate(multiplier=None):
    steps = [{"type": "CHANGE_PER_SECOND", "parameters": [""]}]
    if multiplier:
        steps.append({"type": "MULTIPLIER", "parameters": [str(multiplier)]})
    return steps


# item keys (all contain {#SNMPINDEX}, as LLD requires)
K_OPER = "netops.if.oper[{#SNMPINDEX}]"
K_IN = "netops.if.in[{#SNMPINDEX}]"
K_OUT = "netops.if.out[{#SNMPINDEX}]"
K_HSPEED = "netops.if.hspeed[{#SNMPINDEX}]"
K_SPEED = "netops.if.speed[{#SNMPINDEX}]"
K_EIN = "netops.if.errin[{#SNMPINDEX}]"
K_EOUT = "netops.if.errout[{#SNMPINDEX}]"
K_DIN = "netops.if.discin[{#SNMPINDEX}]"
K_DOUT = "netops.if.discout[{#SNMPINDEX}]"

SPEED_JS = (
    "var exp = Number('" + ctx("SPEED.EXPECTED") + "');\n"
    "var mbps = Number(value);\n"
    "if (exp > 0) { return exp; }\n"
    "return mbps * 1000000;"
)


def item_prototypes():
    poll = ctx("POLL")
    slow = ctx("POLL.SLOW")
    return [
        _item("Interface {#IFNAME}: Operational status", K_OPER, "1.3.6.1.2.1.2.2.1.8.{#SNMPINDEX}",
              poll, "UNSIGNED", ""),
        _item("Interface {#IFNAME}: Bits received", K_IN, "1.3.6.1.2.1.31.1.1.1.6.{#SNMPINDEX}",
              poll, "FLOAT", "bps", _rate(8)),
        _item("Interface {#IFNAME}: Bits sent", K_OUT, "1.3.6.1.2.1.31.1.1.1.10.{#SNMPINDEX}",
              poll, "FLOAT", "bps", _rate(8)),
        _item("Interface {#IFNAME}: Reported speed (ifHighSpeed)", K_HSPEED,
              "1.3.6.1.2.1.31.1.1.1.15.{#SNMPINDEX}", slow, "UNSIGNED", "Mbps"),
        _item("Interface {#IFNAME}: Capacity used for utilization", K_SPEED, None, None, "FLOAT", "bps",
              [{"type": "JAVASCRIPT", "parameters": [SPEED_JS]}], item_type="DEPENDENT", master=K_HSPEED),
        _item("Interface {#IFNAME}: Inbound errors", K_EIN, "1.3.6.1.2.1.2.2.1.14.{#SNMPINDEX}",
              slow, "FLOAT", "eps", _rate()),
        _item("Interface {#IFNAME}: Outbound errors", K_EOUT, "1.3.6.1.2.1.2.2.1.20.{#SNMPINDEX}",
              slow, "FLOAT", "eps", _rate()),
        _item("Interface {#IFNAME}: Inbound discards", K_DIN, "1.3.6.1.2.1.2.2.1.13.{#SNMPINDEX}",
              slow, "FLOAT", "dps", _rate()),
        _item("Interface {#IFNAME}: Outbound discards", K_DOUT, "1.3.6.1.2.1.2.2.1.19.{#SNMPINDEX}",
              slow, "FLOAT", "dps", _rate()),
    ]


def _ref(key):
    return "/%s/%s" % (TEMPLATE_NAME, key)


def _last(key):
    return "last(%s)" % _ref(key)


def _prototype_tags(alert, direction="-", threshold="-", severity=""):
    return [
        {"tag": TAG_ALERT, "value": alert},
        {"tag": "if_name", "value": "{#IFNAME}"},
        {"tag": "if_descr", "value": ctx("DESCR")},
        {"tag": "if_role", "value": ctx("ROLE")},
        {"tag": "link_id", "value": ctx("LINKID")},
        {"tag": "site", "value": "{$NETOPS.SITE}"},
        {"tag": "direction", "value": direction},
        {"tag": "threshold", "value": threshold},
        {"tag": "severity_label", "value": severity},
    ]


def _who():
    return '{$NETOPS.SITE} {HOST.NAME} {#IFNAME} ({$NETOPS.DESCR:"{#IFNAME}"}) [{$NETOPS.ROLE:"{#IFNAME}"}]'


def trigger_prototypes():
    out = []
    sev_gate = '{$NETOPS.SEV:"{#IFNAME}"}=%d'
    for sev_name, prio, label in SEVERITY_VARIANTS:
        gate = sev_gate % prio

        def trig(alert, name, expr, rec=None, direction="-", threshold="-", opdata="", deps=None,
                 desc=""):
            t = {
                "uuid": uuid_for("trigger:%s:%s" % (alert, sev_name)),
                "name": name,
                "event_name": name,
                "opdata": opdata,
                "expression": expr,
                "priority": label,
                "description": desc,
                "manual_close": "YES",
                "tags": _prototype_tags(alert, direction, threshold, sev_name),
            }
            if rec:
                t["recovery_mode"] = "RECOVERY_EXPRESSION"
                t["recovery_expression"] = rec
            if deps:
                t["dependencies"] = deps
            return t

        flap_name = "%s Interface FLAPPING" % _who()
        flap_expr = ("%s=1 and %s and changecount(%s,%s)>=%s" % (
            ctx("FLAP.ON"), gate, _ref(K_OPER), ctx("FLAP.WINDOW"), ctx("FLAP.COUNT")))
        out.append(trig("flapping", flap_name, flap_expr,
                        opdata="status now {ITEM.LASTVALUE1} (1=up)",
                        desc="Link changed state at least FLAP.COUNT times inside FLAP.WINDOW. One "
                             "problem for the whole bounce storm; the Link DOWN problem stays open "
                             "(no further DOWN/UP messages) until the link has been quiet."))

        # No dependency on the flapping trigger: the FIRST down is always reported on the next poll.
        # While changecount() says the link is bouncing, the Link DOWN problem cannot RECOVER, so
        # repeated down/up cycles stay one open problem instead of a stream of messages; if the link
        # ends up down the problem simply remains open (persistent outage stays visible).
        link_recovery = "%s=1 and (%s=0 or changecount(%s,%s)<%s)" % (
            _last(K_OPER), ctx("FLAP.ON"), _ref(K_OPER), ctx("FLAP.WINDOW"), ctx("FLAP.COUNT"))
        out.append(trig(
            "link_down", "%s Interface DOWN" % _who(),
            "%s=1 and %s and %s<>1" % (ctx("LINK"), gate, _last(K_OPER)), link_recovery,
            opdata="ifOperStatus {ITEM.LASTVALUE1} (1=up)",
            desc="Latest polled ifOperStatus is not up(1). Evaluated on every poll of the item; "
                 "no delay window. Recovers when the link is up and no longer flapping."))

        for direction, key in (("RX", K_IN), ("TX", K_OUT)):
            # sample first, capacity second: {ITEM.LASTVALUE1}/{ITEM.LASTVALUE2} follow this order
            problem = ("%s=1 and %s and %s*100>%s*%s and %s>0" % (
                ctx("UTIL.ON"), gate, _last(key), ctx("UTIL.MAX"), _last(K_SPEED), _last(K_SPEED)))
            recovery = "%s*100<%s*%s" % (_last(key), ctx("UTIL.RECOVER"), _last(K_SPEED))
            out.append(trig(
                "util_" + direction.lower(),
                "%s %s utilization HIGH {$NETOPS.UTIL.MAX:\"{#IFNAME}\"}%%" % (_who(), direction),
                problem, recovery, direction=direction, threshold=ctx("UTIL.MAX"),
                opdata="%s now {ITEM.LASTVALUE1}, capacity {ITEM.LASTVALUE2}" % direction,
                desc="Newest %s sample as a percentage of link capacity above UTIL.MAX. Recovers "
                     "only below UTIL.RECOVER, so it cannot toggle around the threshold." % direction))

        for alert, label_, k_in, k_out, on, rate, rec in (
                ("errors", "error rate", K_EIN, K_EOUT, "ERR.ON", "ERR.RATE", "ERR.RECOVER"),
                ("discards", "discard rate", K_DIN, K_DOUT, "DISC.ON", "DISC.RATE", "DISC.RECOVER")):
            problem = "%s=1 and %s and (%s>%s or %s>%s)" % (
                ctx(on), gate, _last(k_in), ctx(rate), _last(k_out), ctx(rate))
            recovery = "%s<=%s and %s<=%s" % (_last(k_in), ctx(rec), _last(k_out), ctx(rec))
            out.append(trig(
                alert, "%s Interface %s HIGH" % (_who(), label_), problem, recovery,
                opdata="in {ITEM.LASTVALUE1}/s out {ITEM.LASTVALUE2}/s",
                desc="Rate computed from the newest two counter samples."))

        out.append(trig(
            "speed_degraded", "%s Interface speed BELOW EXPECTED" % _who(),
            "%s>0 and %s and %s=1 and %s*1000000<%s" % (
                ctx("SPEED.EXPECTED"), gate, _last(K_OPER), _last(K_HSPEED), ctx("SPEED.EXPECTED")),
            opdata="reported {ITEM.LASTVALUE2} Mbps",
            desc="Only active when expected_speed is set for the interface in interfaces.yaml."))
    return out


def discovery_rule():
    items = item_prototypes()
    trig = trigger_prototypes()
    return {
        "uuid": uuid_for("lld:netops.if.discovery"),
        "name": "NETOPS selected interfaces",
        "type": "SNMP_AGENT",
        "snmp_oid": "discovery[{#IFNAME},1.3.6.1.2.1.31.1.1.1.1]",
        "key": "netops.if.discovery",
        "delay": "5m",
        "filter": {"evaltype": "AND_OR", "conditions": [
            {"macro": "{#IFNAME}", "value": "{$NETOPS.IF.MATCH}", "operator": "MATCHES_REGEX",
             "formulaid": "A"}]},
        "lifetime_type": "DELETE_IMMEDIATELY",
        "description": "Only interfaces listed in interfaces.yaml are discovered here. " + MARKER,
        "item_prototypes": items,
        "trigger_prototypes": trig,
    }


def build_payload(tpl_hash=""):
    desc = "%s version=%s hash=%s" % (MARKER, TOOL_VERSION, tpl_hash)
    return {"zabbix_export": {
        "version": "7.0",
        "template_groups": [{"uuid": uuid_for("group:" + TEMPLATE_GROUP), "name": TEMPLATE_GROUP}],
        "templates": [{
            "uuid": uuid_for("template:" + TEMPLATE_NAME),
            "template": TEMPLATE_NAME,
            "name": TEMPLATE_NAME,
            "description": desc,
            "groups": [{"name": TEMPLATE_GROUP}],
            "discovery_rules": [discovery_rule()],
            "macros": [{"macro": m, "value": v, "description": d} for m, v, d in TEMPLATE_MACROS],
        }],
    }}


def content_hash():
    payload = build_payload("")
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def build():
    """Final import document (hash embedded in the template description)."""
    return build_payload(content_hash())


IMPORT_RULES = {
    "template_groups": {"createMissing": True, "updateExisting": False},
    "templates": {"createMissing": True, "updateExisting": True},
    "discoveryRules": {"createMissing": True, "updateExisting": True, "deleteMissing": True},
    "items": {"createMissing": True, "updateExisting": True, "deleteMissing": True},
    "triggers": {"createMissing": True, "updateExisting": True, "deleteMissing": True},
}


def fingerprint_items(doc):
    """Comparable structure derived from the import document (or from live API reads)."""
    tpl = doc["zabbix_export"]["templates"][0]
    rule = tpl["discovery_rules"][0]
    # dependent items have no delay in the export; the API reports them as "0"
    items = sorted((i["key"], i.get("snmp_oid", ""), i.get("delay", "0")) for i in rule["item_prototypes"])
    trigs = sorted((t["name"], _norm(t["expression"]), _norm(t.get("recovery_expression", "")), t["priority"])
                   for t in rule["trigger_prototypes"])
    return {"items": items, "triggers": trigs, "macros": sorted(
        (m["macro"], m["value"]) for m in tpl["macros"])}


PRIORITY_NUM = {"INFO": 1, "WARNING": 2, "AVERAGE": 3, "HIGH": 4, "DISASTER": 5}


def fingerprint_live(items, trigger_prototypes_, macros):
    """Same structure from item.get / triggerprototype.get / usermacro.get output."""
    return {
        "items": sorted((i["key_"], i.get("snmp_oid", ""), i.get("delay", "")) for i in items),
        "triggers": sorted((t["description"], _norm(t["expression"]), _norm(t.get("recovery_expression", "")),
                            int(t["priority"])) for t in trigger_prototypes_),
        "macros": sorted((m["macro"], m["value"]) for m in macros),
    }


def fingerprint_desired_numeric(doc):
    fp = copy.deepcopy(fingerprint_items(doc))
    fp["triggers"] = sorted((n, e, r, PRIORITY_NUM[p]) for n, e, r, p in fp["triggers"])
    return fp


def _norm(expr):
    """Expression text with all whitespace removed, so server-side reformatting is not 'drift'."""
    return re.sub(r"\s+", "", expr or "")

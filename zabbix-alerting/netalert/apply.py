"""Execute a plan. Every mutation is a ZabbixClient call — nothing else writes."""
import json

from . import planner
from . import template as tpl
from .envsafety import IDENTITY_MACRO, IDENTITY_MARKER
from .zbx import ZabbixError


class ApplyError(Exception):
    def __init__(self, message, done):
        Exception.__init__(self, message)
        self.done = done


ORDER = ["init_identity", "import_template", "link_template", "macro_create", "macro_update",
         "unlink_template", "macro_delete", "action_create", "action_update"]


def execute(client, plan, log):
    """Run plan.changes in dependency order. Returns (done_count, warnings)."""
    by = {}
    for ch in plan.changes:
        by.setdefault(ch.action, []).append(ch)
    unknown = set(by) - set(ORDER)
    if unknown:
        raise ApplyError("plan contains unknown actions: %s" % sorted(unknown), 0)
    done = 0
    warnings = []
    templateid = None

    def step(label, method, params):
        try:
            res = client.call(method, params)
        except ZabbixError as exc:
            raise ApplyError("%s failed: %s" % (label, exc), done)
        log("  ok  %s" % label)
        return res

    for action in ORDER:
        chs = by.get(action)
        if not chs:
            continue
        if action == "init_identity":
            step("create global macro %s" % IDENTITY_MACRO, "usermacro.createglobal",
                 {"macro": IDENTITY_MACRO, "value": chs[0].args["value"], "description": IDENTITY_MARKER})
            done += 1
        elif action == "import_template":
            step("import template '%s'" % tpl.TEMPLATE_NAME, "configuration.import",
                 {"format": "json", "source": json.dumps(tpl.build()), "rules": tpl.IMPORT_RULES})
            done += 1
        elif action == "link_template":
            templateid = templateid or planner.get_template(client)["templateid"]
            for ch in chs:
                step("link template to %s" % ch.args["host"], "host.massadd",
                     {"hosts": [{"hostid": ch.args["hostid"]}], "templates": [{"templateid": templateid}]})
                done += 1
        elif action == "macro_create":
            step("create %d macro(s)" % len(chs), "usermacro.create",
                 [{"hostid": c.args["hostid"], "macro": c.args["macro"], "value": c.args["value"],
                   "description": tpl.MARKER} for c in chs])
            done += len(chs)
        elif action == "macro_update":
            step("update %d macro(s)" % len(chs), "usermacro.update",
                 [{"hostmacroid": c.args["hostmacroid"], "value": c.args["value"],
                   "description": tpl.MARKER} for c in chs])
            done += len(chs)
        elif action == "unlink_template":
            tid = planner.get_template(client)["templateid"]
            for ch in chs:
                step("unlink template from %s" % ch.args["host"], "host.massremove",
                     {"hostids": [ch.args["hostid"]], "templateids_clear": [tid]})
                done += 1
        elif action == "macro_delete":
            step("delete %d macro(s)" % len(chs), "usermacro.delete",
                 [c.args["hostmacroid"] for c in chs])
            done += len(chs)
        elif action == "action_create":
            step("create action '%s'" % chs[0].target, "action.create", chs[0].args["params"])
            done += 1
        elif action == "action_update":
            step("update action '%s'" % chs[0].target, "action.update", chs[0].args["params"])
            done += 1
    return done, warnings


def run_discovery(client, host_names, log):
    """Ask Zabbix to run the LLD rule now instead of waiting for its 5m schedule. Best effort."""
    warnings = []
    for name in host_names:
        try:
            h = client.call("host.get", {"output": ["hostid"], "filter": {"host": [name]}})
            if not h:
                continue
            rules = client.call("discoveryrule.get", {"output": ["itemid"], "hostids": [h[0]["hostid"]],
                                                       "filter": {"key_": "netops.if.discovery"}})
            for r in rules:
                client.call("task.create", [{"type": 6, "request": {"itemid": r["itemid"]}}])
                log("  ok  discovery queued on %s" % name)
        except ZabbixError as exc:
            warnings.append("could not queue discovery on %s (%s); it will run on its 5m schedule" %
                            (name, exc.message))
    return warnings

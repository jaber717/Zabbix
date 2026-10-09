#!/usr/bin/env python3
"""v0.3.1: the SAME five sequences as qa/acceptance_v03_security_repro.py (Codex's independent reproductions), run one by one so that each outcome is
reported. A sequence prints FIXED when the unsafe behaviour is no longer reproducible (the manager refused / reported a conflict), REPRODUCED otherwise.
Offline: a fake transport only; never connects to Zabbix. Exit 0 only if all five are FIXED."""
import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from hwh import template, tplmgr, vendordefs
from hwh.api import AuditError, ZabbixAPI
from tests.test_v03_tplmgr import FakeTpl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEF = vendordefs.load_dir(os.path.join(ROOT, "vendors"))["cisco-iosxe"]
NAME = template.template_name(DEF)
MARKER = template.build(DEF)["zabbix_export"]["templates"][0]["description"]
results = []


def api(fake):
    return ZabbixAPI("http://offline.invalid", "fake", transport=fake, write_templates=True)


def verdict(label, fixed, detail=""):
    print("%s: %s%s" % (label, "FIXED" if fixed else "REPRODUCED", (" - " + detail) if detail else ""))
    results.append(fixed)


def refused(fn):
    try:
        fn()
    except AuditError as exc:
        return str(exc)[:150]
    return None


with tempfile.TemporaryDirectory() as base:
    foreign = FakeTpl({"templateid": "501", "host": NAME, "description": MARKER.replace("hash=" + template.content_hash(DEF), "hash=" + "0" * 64), "hosts": []})
    p = tplmgr.plan(api(foreign), "lab", DEF)
    why = refused(lambda: tplmgr.apply(api(foreign), "lab", DEF, base))
    verdict("1 copied-marker foreign template imported", p["action"] != "update" and bool(p["conflicts"]) and why is not None and "configuration.import" not in foreign.calls, why or "")

with tempfile.TemporaryDirectory() as base:
    manual = FakeTpl({"templateid": "502", "host": NAME, "description": MARKER, "hosts": [], "operator_item": "manual-change"})
    p = tplmgr.plan(api(manual), "lab", DEF)
    why = refused(lambda: tplmgr.apply(api(manual), "lab", DEF, base))
    ok_foreign = p["action"] != "noop" and why is not None and "configuration.import" not in manual.calls
    # and the real drift case: a template this deployment OWNS, edited by an operator while the description (and so its hash) stays unchanged
    with tempfile.TemporaryDirectory() as base2:
        mine = FakeTpl()
        tplmgr.apply(api(mine), "lab", DEF, base2)
        before = mine.t["description"]
        mine.gui_edit()
        p2 = tplmgr.plan(api(mine), "lab", DEF, base2)
        n = mine.calls.count("configuration.import")
        why2 = refused(lambda: tplmgr.apply(api(mine), "lab", DEF, base2))
        ok_owned = mine.t["description"] == before and p2["action"] != "noop" and any("DRIFT" in c for c in p2["conflicts"]) and why2 is not None and mine.calls.count("configuration.import") == n
    verdict("2 manual content drift invisible with same marker", ok_foreign and ok_owned, "owned-template drift: %s" % "; ".join(p2["drift"]))

with tempfile.TemporaryDirectory() as base:
    created = FakeTpl()
    tplmgr.apply(api(created), "lab", DEF, base)
    original_id = created.t["templateid"]
    created.t = {"templateid": "999", "host": NAME, "description": MARKER, "hosts": []}
    result = tplmgr.rollback(api(created), "lab", NAME, base)
    verdict("3 rollback deletes recreated same-name template", result["result"] != "deleted" and created.t is not None and "template.delete" not in created.calls,
            "result=%s, recreated id 999 untouched (recorded id %s)" % (result["result"], original_id))

with tempfile.TemporaryDirectory() as base:
    # the unmodified Codex scenario: a linked, marker-bearing template with no record
    linked = FakeTpl({"templateid": "503", "host": NAME, "description": MARKER.replace("hash=" + template.content_hash(DEF), "hash=" + "0" * 64),
                      "hosts": [{"hostid": "600", "host": "live-host"}]})
    p = tplmgr.plan(api(linked), "lab", DEF)
    why = refused(lambda: tplmgr.apply(api(linked), "lab", DEF, base))
    ok1 = bool(p["conflicts"]) and why is not None and "configuration.import" not in linked.calls
    # and the real linked case: a template this deployment OWNS that has since been linked
    owned = FakeTpl()
    tplmgr.apply(api(owned), "lab", DEF, base)
    owned.t["hosts"] = [{"hostid": "600", "host": "live-host"}]
    changed = dict(DEF, sensors=[dict(s) for s in DEF["sensors"]])
    changed["sensors"][0] = dict(changed["sensors"][0], title="changed title")
    p2 = tplmgr.plan(api(owned), "lab", changed, base)
    n = owned.calls.count("configuration.import")
    why2 = refused(lambda: tplmgr.apply(api(owned), "lab", changed, base))
    verdict("4 linked template update not blocked", ok1 and any("linked to 1 host(s) (ids 600)" in c for c in p2["conflicts"]) and why2 is not None and owned.calls.count("configuration.import") == n,
            "linked ids reported: %s" % p2["linked_host_ids"])

rules = template.IMPORT_RULES
verdict("5 deleteMissing enabled for template children", not any(rules[k].get("deleteMissing") for k in rules) and all("deleteMissing" in rules[k] for k in ("discoveryRules", "items", "triggers")),
        "IMPORT_RULES deleteMissing = %s" % dict((k, rules[k]["deleteMissing"]) for k in ("discoveryRules", "items", "triggers", "valueMaps")))

print("ALL FIVE FIXED" if all(results) else "NOT ALL FIXED")
sys.exit(0 if all(results) else 1)

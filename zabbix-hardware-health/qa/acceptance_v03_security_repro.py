#!/usr/bin/env python3
"""Independent, offline template-manager safety reproductions; never connects to Zabbix."""
import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from hwh import template, tplmgr, vendordefs
from hwh.api import ZabbixAPI
from tests.test_v03_tplmgr import FakeTpl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEF = vendordefs.load_dir(os.path.join(ROOT, "vendors"))["cisco-iosxe"]
NAME = template.template_name(DEF)
MARKER = template.build(DEF)["zabbix_export"]["templates"][0]["description"]


def api(fake):
    return ZabbixAPI("http://offline.invalid", "fake", transport=fake, write_templates=True)


def check(label, condition):
    print("%s: %s" % (label, "CONFIRMED" if condition else "NOT REPRODUCED"))
    if not condition:
        raise AssertionError(label)


with tempfile.TemporaryDirectory() as base:
    # Marker text is copyable; no ownership nonce, ledger or bound template ID exists.
    foreign = FakeTpl({"templateid": "501", "host": NAME, "description": MARKER.replace(
        "hash=" + template.content_hash(DEF), "hash=" + "0" * 64), "hosts": []})
    p = tplmgr.plan(api(foreign), "lab", DEF)
    result = tplmgr.apply(api(foreign), "lab", DEF, base)
    check("copied-marker foreign template imported", p["action"] == "update" and
          result["result"] == "applied" and "configuration.import" in foreign.calls)

with tempfile.TemporaryDirectory() as base:
    manual = FakeTpl({"templateid": "502", "host": NAME, "description": MARKER,
                      "hosts": [], "operator_item": "manual-change"})
    p = tplmgr.plan(api(manual), "lab", DEF)
    result = tplmgr.apply(api(manual), "lab", DEF, base)
    check("manual content drift invisible with same marker", p["action"] == "noop" and
          result["result"] == "unchanged" and "configuration.export" not in manual.calls)

with tempfile.TemporaryDirectory() as base:
    created = FakeTpl()
    tplmgr.apply(api(created), "lab", DEF, base)
    original_id = created.t["templateid"]
    created.t = {"templateid": "999", "host": NAME, "description": MARKER, "hosts": []}
    result = tplmgr.rollback(api(created), "lab", NAME, base)
    check("rollback deletes recreated same-name template", original_id != "999" and
          result["result"] == "deleted" and created.t is None)

with tempfile.TemporaryDirectory() as base:
    linked = FakeTpl({"templateid": "503", "host": NAME, "description": MARKER.replace(
        "hash=" + template.content_hash(DEF), "hash=" + "0" * 64),
                      "hosts": [{"hostid": "600", "host": "live-host"}]})
    p = tplmgr.plan(api(linked), "lab", DEF)
    tplmgr.apply(api(linked), "lab", DEF, base)
    check("linked template update not blocked", p["action"] == "update" and
          "configuration.import" in linked.calls)

rules = template.IMPORT_RULES
check("deleteMissing enabled for template children", all(rules[k]["deleteMissing"]
      for k in ("discoveryRules", "items", "triggers")))

import io
import json
import os
import tempfile
import unittest

from hwh import template, tplmgr, vendordefs
from hwh.api import AuditError, ZabbixAPI

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEF = vendordefs.load_dir(os.path.join(ROOT, "vendors"))["cisco-iosxe"]


class _R(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeTpl(object):
    def __init__(self, existing=None):
        self.t = existing            # dict or None
        self.calls = []

    def __call__(self, req, timeout=0):
        b = json.loads(req.data)
        m, p = b["method"], b.get("params")
        self.calls.append(m)
        if m == "template.get":
            r = [dict(self.t, hosts=self.t.get("hosts", []))] if self.t else []
        elif m == "configuration.export":
            r = json.dumps({"old": self.t})
        elif m == "configuration.import":
            src = json.loads(p["source"])
            if "old" in src:
                self.t = src["old"]
            else:
                tm = src["zabbix_export"]["templates"][0]
                self.t = {"templateid": "900", "host": tm["template"], "description": tm["description"], "hosts": []}
            r = True
        elif m == "template.delete":
            self.t = None
            r = {"templateids": p}
        else:
            raise AssertionError(m)
        return _R(json.dumps({"jsonrpc": "2.0", "id": b["id"], "result": r}).encode())


def api(fake, writes=True):
    return ZabbixAPI("http://z", "t", transport=fake, write_templates=writes)


class TplMgr(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp()

    def test_create_then_noop_then_rollback_deletes(self):
        f = FakeTpl()
        a = api(f)
        self.assertEqual(tplmgr.plan(a, "lab", DEF)["action"], "create")
        self.assertEqual(tplmgr.apply(a, "lab", DEF, self.base)["result"], "applied")
        self.assertEqual(tplmgr.plan(a, "lab", DEF)["action"], "noop")
        self.assertEqual(tplmgr.rollback(a, "lab", template.template_name(DEF), self.base)["result"], "deleted")
        self.assertIsNone(f.t)

    def test_foreign_template_is_conflict_and_untouched(self):
        f = FakeTpl({"templateid": "5", "host": template.template_name(DEF), "description": "operator's own", "hosts": []})
        a = api(f)
        self.assertTrue(tplmgr.plan(a, "lab", DEF)["conflicts"])
        with self.assertRaises(AuditError):
            tplmgr.apply(a, "lab", DEF, self.base)
        self.assertNotIn("configuration.import", f.calls)

    def test_other_definition_marker_is_conflict(self):
        f = FakeTpl({"templateid": "5", "host": template.template_name(DEF), "hosts": [],
                     "description": "managed_by=netops-hardware-health version=1.0 definition=other hash=abc"})
        self.assertTrue(tplmgr.plan(api(f), "lab", DEF)["conflicts"])

    def test_production_refused(self):
        self.assertTrue(tplmgr.plan(api(FakeTpl()), "production", DEF)["conflicts"])

    def test_writes_disabled_by_default(self):
        with self.assertRaises(AuditError):
            tplmgr.apply(api(FakeTpl(), writes=False), "lab", DEF, self.base)
        with self.assertRaises(AuditError):
            api(FakeTpl(), writes=False).call("configuration.import", {})

    def test_rollback_refuses_linked_template(self):
        f = FakeTpl()
        a = api(f)
        tplmgr.apply(a, "lab", DEF, self.base)
        f.t["hosts"] = [{"hostid": "1", "host": "x"}]
        with self.assertRaises(AuditError):
            tplmgr.rollback(a, "lab", template.template_name(DEF), self.base)
        self.assertIsNotNone(f.t)

    def test_update_restores_previous_export(self):
        f = FakeTpl({"templateid": "7", "host": template.template_name(DEF), "hosts": [],
                     "description": "managed_by=netops-hardware-health version=1.0 definition=cisco-iosxe hash=0000"})
        a = api(f)
        old = dict(f.t)
        self.assertEqual(tplmgr.plan(a, "lab", DEF)["action"], "update")
        tplmgr.apply(a, "lab", DEF, self.base)
        self.assertNotEqual(f.t["description"], old["description"])
        self.assertEqual(tplmgr.rollback(a, "lab", template.template_name(DEF), self.base)["result"], "restored")
        self.assertEqual(f.t["description"], old["description"])


if __name__ == "__main__":
    unittest.main()

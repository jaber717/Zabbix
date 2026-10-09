import copy
import io
import json
import os
import tempfile
import unittest

from hwh import template, tplmgr, vendordefs
from hwh.api import AuditError, ZabbixAPI

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFS = vendordefs.load_dir(os.path.join(ROOT, "vendors"))
DEF = DEFS["cisco-iosxe"]
NAME = template.template_name(DEF)
UUID = template.build(DEF)["zabbix_export"]["templates"][0]["uuid"]


class _R(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def keys_of(doc):
    t = doc["zabbix_export"]["templates"][0]
    ks = dict((i["key"], i) for i in t.get("items", []))
    for r in t.get("discovery_rules", []):
        for ip in r.get("item_prototypes", []):
            ks[ip["key"]] = ip
    return ks


class FakeZ(object):
    """A small stateful Zabbix: one template slot, template.get / export / import / importcompare / delete, call log and per-call hooks."""

    def __init__(self, compare=True):
        self.t = None                 # {"templateid","host","uuid","description","hosts","doc"}
        self.calls = []
        self.hooks = {}               # (method, nth) -> fn(self)
        self.compare = compare
        self.compare_error = None
        self.next_id = 900
        self.count = {}

    # ------------------------------------------------------------------ helpers for tests
    def put_foreign(self, host=NAME, uuid="f" * 32, description="", hosts=()):
        self.next_id += 1
        self.t = {"templateid": str(self.next_id), "host": host, "uuid": uuid, "description": description, "hosts": list(hosts), "doc": None}

    def link(self):
        self.t["hosts"] = [{"hostid": "1", "host": "linked-host"}]

    def gui_edit(self):
        doc = self.t["doc"]
        tm = doc["zabbix_export"]["templates"][0]
        tm.setdefault("items", []).append({"uuid": "a" * 32, "name": "operator added", "key": "operator.added", "type": "TRAP"})

    def methods(self):
        return [c for c in self.calls]

    # ------------------------------------------------------------------ transport
    def __call__(self, req, timeout=0):
        b = json.loads(req.data)
        m, p = b["method"], b.get("params")
        self.calls.append(m)
        n = self.count[m] = self.count.get(m, 0) + 1
        h = self.hooks.get((m, n))
        if h:
            h(self)
        try:
            r = self.handle(m, p)
            body = {"jsonrpc": "2.0", "id": b["id"], "result": r}
        except KeyError as exc:
            body = {"jsonrpc": "2.0", "id": b["id"], "error": {"code": -32500, "message": "Application error.", "data": str(exc)}}
        except RuntimeError as exc:
            body = {"jsonrpc": "2.0", "id": b["id"], "error": {"code": -32601, "message": str(exc), "data": ""}}
        return _R(json.dumps(body).encode())

    def view(self):
        t = self.t
        return {"templateid": t["templateid"], "host": t["host"], "name": t["host"], "uuid": t["uuid"], "description": t["description"], "hosts": list(t["hosts"])}

    def handle(self, m, p):
        if m == "template.get":
            if not self.t:
                return []
            flt = p.get("filter") or {}
            if "host" in flt and self.t["host"] not in flt["host"]:
                return []
            if "uuid" in flt and self.t["uuid"] not in flt["uuid"]:
                return []
            if p.get("templateids") and self.t["templateid"] not in p["templateids"]:
                return []
            return [self.view()]
        if m == "configuration.export":
            tid = p["options"]["templates"][0]
            if not self.t or self.t["templateid"] != tid or self.t["doc"] is None:
                raise KeyError("no such template " + tid)
            return json.dumps(self.t["doc"])
        if m == "configuration.import":
            src = json.loads(p["source"])
            tm = src["zabbix_export"]["templates"][0]
            if self.t and self.t["uuid"] == tm["uuid"]:
                tid, hosts = self.t["templateid"], self.t["hosts"]
            else:
                self.next_id += 1
                tid, hosts = str(self.next_id), []
            self.t = {"templateid": tid, "host": tm["template"], "uuid": tm["uuid"], "description": tm["description"], "hosts": hosts, "doc": copy.deepcopy(src)}
            return True
        if m == "configuration.importcompare":
            if not self.compare:
                raise RuntimeError('Incorrect method "configuration.importcompare".')
            if self.compare_error:
                raise RuntimeError(self.compare_error)
            src = json.loads(p["source"])
            tm = src["zabbix_export"]["templates"][0]
            if not self.t or self.t["uuid"] != tm["uuid"]:
                return {"templates": {"added": [{"after": {"uuid": tm["uuid"], "template": tm["template"], "name": tm["name"]}}]}}
            old, new = keys_of(self.t["doc"]), keys_of(src)
            items = {"added": [{"after": {"key": k, "name": new[k]["name"]}} for k in sorted(set(new) - set(old))],
                     "removed": [{"before": {"key": k, "name": old[k]["name"]}} for k in sorted(set(old) - set(new))],
                     "updated": [{"before": {"key": k, "name": old[k]["name"]}, "after": {"key": k, "name": new[k]["name"]}} for k in sorted(set(old) & set(new))
                                 if json.dumps(old[k], sort_keys=True) != json.dumps(new[k], sort_keys=True)]}
            items = dict((k, v) for k, v in items.items() if v)
            entry = {"before": {"uuid": tm["uuid"], "template": self.t["host"], "name": self.t["host"]}, "after": {"uuid": tm["uuid"], "template": tm["template"], "name": tm["name"]}}
            if items:
                entry["items"] = items
            return {"templates": {"updated": [entry]}}
        if m == "template.delete":
            if self.t and self.t["templateid"] in p:
                self.t = None
            return {"templateids": p}
        raise AssertionError("unexpected method " + m)


def api_for(fz, writes=True):
    return ZabbixAPI("http://z", "t", transport=fz, write_templates=writes)


def changed_def():
    d = copy.deepcopy(DEF)
    for sn in d["sensors"]:
        for t in sn.get("triggers") or []:
            if t["states"] == ["failed"]:
                t["confirm_samples"] = 3
    return d


def reduced_def():
    d = copy.deepcopy(DEF)
    d["sensors"] = d["sensors"][:-1]
    return d


class Base(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.fz = FakeZ()
        self.api = api_for(self.fz)

    def plan(self, d=DEF, **kw):
        return tplmgr.plan(self.api, "lab", d, self.base, **kw)

    def apply(self, d=DEF, **kw):
        return tplmgr.apply(self.api, "lab", d, self.base, **kw)

    def rollback(self, d=DEF, **kw):
        return tplmgr.rollback(self.api, "lab", d, self.base, **kw)

    def imports(self):
        return self.fz.calls.count("configuration.import")

    def deletes(self):
        return self.fz.calls.count("template.delete")


class Lifecycle(Base):
    def test_create_records_exact_id_and_nonce_then_is_idempotent(self):
        self.assertEqual(self.plan()["action"], "create")
        r = self.apply()
        self.assertEqual(r["result"], "applied")
        rec = tplmgr.load_record(self.base, "lab", DEF["id"])
        self.assertEqual(rec["templateid"], self.fz.t["templateid"])
        self.assertIn("nonce=" + rec["nonce"], self.fz.t["description"])
        self.assertEqual(rec["state"], "owned")
        self.assertEqual(oct(os.stat(tplmgr.record_path(self.base, "lab", DEF["id"])).st_mode & 0o777), "0o600")
        self.assertEqual(self.plan()["action"], "noop")
        n = self.imports()
        self.assertEqual(self.apply()["result"], "unchanged")
        self.assertEqual(self.imports(), n)

    def test_update_then_rollback_restores_the_exact_original_export(self):
        self.apply()
        _, before = tplmgr.export_live(self.api, self.fz.t["templateid"])
        p = self.plan(changed_def())
        self.assertEqual(p["action"], "update")
        self.assertTrue(p["compare"]["operations"])
        r = self.apply(changed_def())
        self.assertTrue(os.path.isfile(r["backup"]))
        self.assertEqual(r["backup_export_sha256"], before)
        _, mid = tplmgr.export_live(self.api, self.fz.t["templateid"])
        self.assertNotEqual(mid, before)
        self.assertEqual(self.rollback(changed_def())["result"], "restored")
        _, after = tplmgr.export_live(self.api, self.fz.t["templateid"])
        self.assertEqual(after, before)
        self.assertEqual(len(tplmgr.load_record(self.base, "lab", DEF["id"])["steps"]), 1)
        self.assertEqual(self.plan()["action"], "noop")

    def test_rollback_of_a_create_deletes_only_the_recorded_template(self):
        self.apply()
        tid = self.fz.t["templateid"]
        r = self.rollback()
        self.assertEqual((r["result"], r["templateid"]), ("deleted", tid))
        self.assertIsNone(self.fz.t)
        self.assertIsNone(tplmgr.load_record(self.base, "lab", DEF["id"]))

    def test_production_and_disabled_writes_refused(self):
        self.assertTrue(tplmgr.plan(self.api, "production", DEF, self.base)["conflicts"])
        with self.assertRaises(AuditError):
            tplmgr.apply(api_for(self.fz, writes=False), "lab", DEF, self.base)
        with self.assertRaises(AuditError):
            api_for(self.fz, writes=False).call("configuration.import", {})
        with self.assertRaises(AuditError):
            api_for(self.fz, writes=False).call("template.delete", ["1"])


class OwnershipAndAdoption(Base):
    MARKER = "managed_by=netops-hardware-health version=1.0 definition=cisco-iosxe hash=%s" % template.content_hash(DEF)

    def test_copied_marker_is_not_ownership(self):
        self.fz.put_foreign(description=self.MARKER + " nonce=" + "ab" * 12)
        p = self.plan()
        self.assertTrue(any("NO ownership record" in c for c in p["conflicts"]))
        with self.assertRaises(AuditError):
            self.apply()
        self.assertEqual(self.imports(), 0)
        with self.assertRaises(AuditError):
            self.rollback()
        self.assertEqual(self.deletes(), 0)

    def test_foreign_template_with_no_marker_is_never_adopted(self):
        self.fz.put_foreign(description="operator's")
        self.assertTrue(self.plan()["conflicts"])
        with self.assertRaises(AuditError):
            self.apply()
        self.assertEqual(self.imports(), 0)

    def test_same_uuid_under_another_name_is_a_conflict(self):
        self.fz.put_foreign(host="somebody else's copy", uuid=UUID)
        p = self.plan()
        self.assertTrue(any("UUID" in c for c in p["conflicts"]))
        with self.assertRaises(AuditError):
            self.apply()
        self.assertEqual(self.imports(), 0)

    def test_recreated_or_foreign_template_is_never_deleted_by_rollback(self):
        self.apply()
        recorded = self.fz.t["templateid"]
        self.fz.t = None                                              # someone deleted ours ...
        self.fz.put_foreign(description=self.MARKER + " nonce=" + tplmgr.load_record(self.base, "lab", DEF["id"])["nonce"])   # ... and recreated one that even copies the nonce
        self.assertNotEqual(self.fz.t["templateid"], recorded)
        p = self.plan()
        self.assertTrue(any("recreated or is foreign" in c for c in p["conflicts"]))
        r = self.rollback()
        self.assertEqual(r["result"], "already-absent")
        self.assertIn("NOT touched", r["note"])
        self.assertEqual(self.deletes(), 0)
        self.assertIsNotNone(self.fz.t)

    def test_renamed_or_nonce_stripped_template_fails_ownership(self):
        self.apply()
        self.fz.t["description"] = self.fz.t["description"].replace(" nonce=", " x=")
        self.assertTrue(any("nonce" in c for c in self.plan()["conflicts"]))
        with self.assertRaises(AuditError):
            self.rollback()
        self.assertEqual(self.deletes(), 0)

    def test_stale_record_with_nothing_live_allows_a_fresh_create(self):
        self.apply()
        self.fz.t = None
        p = self.plan()
        self.assertEqual(p["action"], "create")
        self.apply()
        self.assertTrue([f for f in os.listdir(os.path.dirname(tplmgr.record_path(self.base, "lab", DEF["id"]))) if "archived" in f])

    def test_unreadable_record_blocks_everything(self):
        self.apply()
        with open(tplmgr.record_path(self.base, "lab", DEF["id"]), "w") as fh:
            fh.write("{broken")
        with self.assertRaises(AuditError):
            self.plan()


class Drift(Base):
    def test_gui_edit_is_drift_and_blocks_apply_and_rollback(self):
        self.apply()
        self.fz.gui_edit()
        p = self.plan(changed_def())
        self.assertTrue(any("DRIFT" in c for c in p["conflicts"]))
        n = self.imports()
        with self.assertRaises(AuditError):
            self.apply(changed_def())
        with self.assertRaises(AuditError):
            self.rollback()
        self.assertEqual(self.imports(), n)
        self.assertEqual(self.deletes(), 0)

    def test_accept_drift_still_surfaces_and_refuses_the_deletion_of_the_edit(self):
        self.apply()
        self.fz.gui_edit()
        p = self.plan(changed_def(), accept_drift=True)
        self.assertTrue(any("DELETED" in c and "operator added" in c for c in p["conflicts"]))
        r = self.apply(changed_def(), accept_drift=True, approve_removals="CHG-1")
        self.assertEqual(r["result"], "applied")
        self.assertFalse(any(i.get("key") == "operator.added" for i in self.fz.t["doc"]["zabbix_export"]["templates"][0].get("items", [])))

    def test_change_between_plan_and_write_is_caught(self):
        self.apply()
        n_exports = self.fz.count.get("configuration.export", 0)
        # plan checks drift (export #1), the write path re-validates (#2): change the template just before that second read
        self.fz.hooks[("configuration.export", n_exports + 2)] = lambda z: z.gui_edit()
        n = self.imports()
        with self.assertRaises(AuditError) as cm:
            self.apply(changed_def())
        self.assertIn("REFUSED at the write", str(cm.exception))
        self.assertEqual(self.imports(), n)

    def test_change_while_backing_up_is_caught(self):
        self.apply()
        n_exports = self.fz.count.get("configuration.export", 0)
        # plan (#1), revalidation (#2), backup export (#3), confirmation re-export (#4): change after the backup was read
        self.fz.hooks[("configuration.export", n_exports + 4)] = lambda z: z.gui_edit()
        n = self.imports()
        with self.assertRaises(AuditError) as cm:
            self.apply(changed_def())
        self.assertIn("changed while it was being backed up", str(cm.exception))
        self.assertEqual(self.imports(), n)


class ImportComparePolicy(Base):
    def test_every_operation_is_surfaced_and_removals_need_approval(self):
        self.apply()
        p = self.plan(reduced_def())
        ops = p["compare"]["operations"]
        self.assertTrue([o for o in ops if o["op"] == "removed"])
        self.assertTrue(any("DELETED" in c for c in p["conflicts"]))
        with self.assertRaises(AuditError):
            self.apply(reduced_def())
        ok = self.plan(reduced_def(), approve_removals="CHG-42")
        self.assertEqual(ok["conflicts"], [])
        self.assertTrue(any("removals approved by 'CHG-42'" in n for n in ok["notes"]))

    def test_short_approval_reference_is_not_accepted(self):
        self.apply()
        self.assertTrue(self.plan(reduced_def(), approve_removals="x")["conflicts"])

    def test_linked_template_update_needs_independent_approval(self):
        self.apply()
        self.fz.link()
        p = self.plan(changed_def())
        self.assertTrue(any("linked to 1 host" in c for c in p["conflicts"]))
        with self.assertRaises(AuditError):
            self.apply(changed_def())
        self.assertEqual(self.plan(changed_def(), approve_linked="CHG-7")["conflicts"], [])
        self.assertEqual(self.apply(changed_def(), approve_linked="CHG-7")["result"], "applied")

    def test_link_appearing_after_planning_is_caught_at_the_write(self):
        self.apply()
        n = self.fz.count.get("template.get", 0)
        orig = self.fz.handle

        def late(m, p):
            r = orig(m, p)
            return r
        # link the template right before the write-time re-read of the template by id (the 2nd by-id read of the apply)
        self.fz.hooks[("configuration.export", self.fz.count.get("configuration.export", 0) + 2)] = lambda z: z.link()
        with self.assertRaises(AuditError) as cm:
            self.apply(changed_def(), approve_linked=None)
        self.assertIn("linked", str(cm.exception))

    def test_importcompare_unavailable_refuses_update_but_allows_create(self):
        fz = FakeZ(compare=False)
        self.fz, self.api = fz, api_for(fz)
        p = self.plan()
        self.assertEqual((p["action"], p["conflicts"]), ("create", []))
        self.assertTrue(any("not available" in n for n in p["notes"]))
        self.apply()
        p2 = self.plan(changed_def())
        self.assertTrue(any("cannot be shown" in c for c in p2["conflicts"]))
        with self.assertRaises(AuditError):
            self.apply(changed_def())

    def test_importcompare_rejection_is_a_conflict(self):
        self.fz.compare_error = "Invalid parameter \"/1/source\": unexpected tag."
        p = self.plan()
        self.assertTrue(any("rejected the generated template" in c for c in p["conflicts"]))
        with self.assertRaises(AuditError):
            self.apply()
        self.assertEqual(self.imports(), 0)

    def test_compare_touching_objects_outside_the_template_is_refused(self):
        ops = [{"op": "updated", "path": "host_groups", "label": "Linux servers", "entry": {}}]
        probs, _ = tplmgr.judge_compare(ops, "update", NAME, None)
        self.assertTrue(any("outside the template" in p for p in probs))

    def test_create_that_would_update_something_is_refused(self):
        ops = [{"op": "updated", "path": "templates", "label": NAME, "entry": {"before": {"template": NAME}, "after": {"template": NAME}}}]
        probs, _ = tplmgr.judge_compare(ops, "create", NAME, None)
        self.assertTrue(any("must only add" in p for p in probs))

    def test_rename_and_template_removal_are_refused(self):
        e = {"before": {"template": NAME}, "after": {"template": "other"}}
        probs, _ = tplmgr.judge_compare([{"op": "updated", "path": "templates", "label": "other", "entry": e}], "update", NAME, None)
        self.assertTrue(any("other than" in p or "RENAME" in p for p in probs))
        probs, _ = tplmgr.judge_compare([{"op": "removed", "path": "templates", "label": NAME, "entry": {"before": {"template": NAME}}}], "update", NAME, "ref-1")
        self.assertTrue(any("remove template" in p for p in probs))

    def test_documented_response_shape_is_flattened(self):
        doc_example = {"templates": {"updated": [{
            "before": {"uuid": "u", "template": "New template", "name": "New template"}, "after": {"uuid": "u", "template": "New template", "name": "New template"},
            "items": {
                "added": [{"after": {"uuid": "a", "name": "CPU utilization", "key": "system.cpu.util"},
                           "triggers": {"added": [{"after": {"uuid": "t", "expression": "avg(/New template/system.cpu.util,3m)>70", "name": "CPU utilization too high"}}]}}],
                "removed": [{"before": {"uuid": "b", "name": "CPU load", "key": "system.cpu.load"},
                             "triggers": {"removed": [{"before": {"uuid": "t2", "name": "CPU load too high"}}]}}],
                "updated": [{"before": {"uuid": "c", "name": "Zabbix agent ping", "key": "agent.ping"}, "after": {"uuid": "c", "name": "Zabbix agent ping", "key": "agent.ping", "delay": "3m"}}]}}]}}
        ops = tplmgr.summarize_compare(doc_example)
        got = sorted((o["op"], o["path"], o["label"]) for o in ops)
        self.assertEqual(got, sorted([("updated", "templates", "New template"), ("added", "templates/items", "CPU utilization (system.cpu.util)"), ("added", "templates/items/triggers", "CPU utilization too high"),
                                      ("removed", "templates/items", "CPU load (system.cpu.load)"), ("removed", "templates/items/triggers", "CPU load too high"), ("updated", "templates/items", "Zabbix agent ping (agent.ping)")]))
        probs, _ = tplmgr.judge_compare(ops, "update", "New template", None)
        self.assertEqual(len([p for p in probs if "DELETED" in p]), 1)
        self.assertIn("2 object(s) would be DELETED", probs[0] if "2 object" in probs[0] else " ".join(probs))


class BackupIntegrity(Base):
    def test_tampered_backup_is_refused_at_rollback(self):
        self.apply()
        r = self.apply(changed_def())
        with open(r["backup"], encoding="utf-8") as fh:
            b = json.load(fh)
        b["export"] = b["export"].replace("fan", "fAN", 1)
        with open(r["backup"], "w", encoding="utf-8") as fh:
            json.dump(b, fh)
        n = self.imports()
        with self.assertRaises(AuditError) as cm:
            self.rollback(changed_def())
        self.assertIn("SHA-256", str(cm.exception))
        self.assertEqual(self.imports(), n)

    def test_restore_that_does_not_reproduce_the_original_is_reported(self):
        self.apply()
        self.apply(changed_def())
        orig = self.fz.handle

        def lossy(m, p):
            r = orig(m, p)
            if m == "configuration.import":
                self.fz.t["doc"]["zabbix_export"]["templates"][0]["items"].append({"uuid": "e" * 32, "name": "x", "key": "x", "type": "TRAP"})
            return r
        self.fz.handle = lossy
        with self.assertRaises(AuditError) as cm:
            self.rollback(changed_def())
        self.assertIn("does not reproduce", str(cm.exception))

    def test_failed_import_leaves_a_pending_record_that_cannot_delete_a_foreign_template(self):
        orig = self.fz.handle

        def wrong_nonce(m, p):
            r = orig(m, p)
            if m == "configuration.import":
                self.fz.t["description"] = self.fz.t["description"].replace("nonce=", "nonce=00")
            return r
        self.fz.handle = wrong_nonce
        with self.assertRaises(AuditError):
            self.apply()
        rec = tplmgr.load_record(self.base, "lab", DEF["id"])
        self.assertEqual(rec["state"], "pending")
        with self.assertRaises(AuditError):
            self.rollback()
        self.assertEqual(self.deletes(), 0)

    def test_pending_record_with_correct_nonce_can_be_rolled_back(self):
        orig = self.fz.handle

        def boom(m, p):
            r = orig(m, p)
            if m == "template.get" and p.get("filter", {}).get("host") and self.fz.count.get("configuration.import") and not getattr(self, "_boomed", False):
                self._boomed = True
                raise KeyError("simulated read failure after a successful import")
            return r
        self.fz.handle = boom
        with self.assertRaises(AuditError):
            self.apply()
        self.fz.handle = orig
        self.assertEqual(tplmgr.load_record(self.base, "lab", DEF["id"])["state"], "pending")
        self.assertEqual(self.rollback()["result"], "deleted")


if __name__ == "__main__":
    unittest.main()

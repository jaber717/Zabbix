"""Template manager: ownership, drift, rollback, linked templates, non-destructive import, immutable backups, races and interrupted operations.

`FakeTpl` is a small stateful Zabbix (one template slot). It is also imported by the independent reproduction script
qa/acceptance_v03_security_repro.py, so its constructor and attributes (`FakeTpl(existing_dict)`, `.t`, `.calls`) are kept compatible."""
import copy
import io
import json
import os
import stat
import tempfile
import unittest

from hwh import template, tplmgr, vendordefs
from hwh.api import AuditError, ZabbixAPI

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFS = vendordefs.load_dir(os.path.join(ROOT, "vendors"))
DEF = DEFS["cisco-iosxe"]
NAME = template.template_name(DEF)
UUID = template.build(DEF)["zabbix_export"]["templates"][0]["uuid"]
MARKER = "managed_by=netops-hardware-health version=1.0 definition=cisco-iosxe hash=%s" % template.content_hash(DEF)


class _R(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _merge(old, new, key, delete):
    if delete:
        return list(new)
    seen = dict((x[key], x) for x in old)
    seen.update(dict((x[key], x) for x in new))
    return list(seen.values())


class FakeTpl(object):
    def __init__(self, existing=None, compare=True):
        self.t = existing
        self.calls = []
        self.import_rules = []
        self.hooks = {}               # (method, nth) -> fn(fake)
        self.count = {}
        self.compare = compare
        self.compare_error = None
        self.compare_override = None  # a fixed importcompare result
        self.next_id = 899
        self.fail_import = None       # exception text raised by configuration.import (nothing applied)

    # ------------------------------------------------------------------ test helpers
    def put_foreign(self, host=NAME, uuid="f" * 32, description="", hosts=(), **extra):
        self.next_id += 1
        self.t = dict({"templateid": str(self.next_id), "host": host, "uuid": uuid, "description": description, "hosts": list(hosts)}, **extra)

    def link(self):
        self.t["hosts"] = [{"hostid": "77", "host": "linked-host"}]

    def doc(self):
        t = self.t
        if t.get("doc"):
            d = copy.deepcopy(t["doc"])               # Zabbix exports each collection in a deterministic order
            tm = d["zabbix_export"]["templates"][0]
            for sec, key in (("items", "key"), ("discovery_rules", "key"), ("valuemaps", "name"), ("macros", "macro")):
                if isinstance(tm.get(sec), list):
                    tm[sec] = sorted(tm[sec], key=lambda x: x.get(key, ""))
            return d
        body = dict((k, v) for k, v in t.items() if k not in ("templateid", "hosts", "doc"))
        body.setdefault("template", t["host"])
        body.setdefault("name", t["host"])
        return {"zabbix_export": {"version": "7.0", "templates": [body]}}

    def tm(self):
        return self.t["doc"]["zabbix_export"]["templates"][0]

    def gui_edit(self):
        self.tm().setdefault("items", []).append({"uuid": "a" * 32, "name": "operator added", "key": "operator.added", "type": "TRAP"})

    def edit_first(self, section, field, value):
        entry = self.tm()[section][0]
        entry[field] = value

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
            body = {"jsonrpc": "2.0", "id": b["id"], "result": self.handle(m, p)}
        except KeyError as exc:
            body = {"jsonrpc": "2.0", "id": b["id"], "error": {"code": -32500, "message": "Application error.", "data": str(exc)}}
        except RuntimeError as exc:
            body = {"jsonrpc": "2.0", "id": b["id"], "error": {"code": -32601, "message": str(exc), "data": ""}}
        return _R(json.dumps(body).encode())

    def view(self):
        t = self.t
        return {"templateid": t["templateid"], "host": t["host"], "name": t["host"], "uuid": t.get("uuid", ""), "description": t.get("description", ""), "hosts": list(t["hosts"])}

    def handle(self, m, p):
        if m == "template.get":
            if not self.t:
                return []
            flt = p.get("filter") or {}
            if "host" in flt and self.t["host"] not in flt["host"]:
                return []
            if "uuid" in flt and self.t.get("uuid", "") not in flt["uuid"]:
                return []
            if p.get("templateids") and self.t["templateid"] not in p["templateids"]:
                return []
            return [self.view()]
        if m == "configuration.export":
            tid = p["options"]["templates"][0]
            if not self.t or self.t["templateid"] != tid:
                raise KeyError("no such template " + tid)
            return json.dumps(self.doc())
        if m == "configuration.import":
            self.import_rules.append(p["rules"])
            if self.fail_import:
                raise RuntimeError(self.fail_import)
            src = json.loads(p["source"])
            tm = src["zabbix_export"]["templates"][0]
            if self.t and self.t.get("uuid") != tm["uuid"] and self.t["host"] == tm["template"]:
                raise RuntimeError("Template \"%s\" already exists." % tm["template"])
            delete = bool(p["rules"].get("items", {}).get("deleteMissing"))
            if self.t and self.t.get("uuid") == tm["uuid"]:
                if not p["rules"]["templates"]["updateExisting"]:
                    return True                                # existing objects are not touched
                old = self.doc()["zabbix_export"]["templates"][0]
                merged = copy.deepcopy(tm)
                merged["items"] = _merge(old.get("items", []), tm.get("items", []), "key", delete)
                merged["discovery_rules"] = _merge(old.get("discovery_rules", []), tm.get("discovery_rules", []), "key", delete)
                merged["valuemaps"] = _merge(old.get("valuemaps", []), tm.get("valuemaps", []), "name", delete)
                merged["macros"] = _merge(old.get("macros", []), tm.get("macros", []), "macro", delete)
                tid, hosts = self.t["templateid"], self.t["hosts"]
                doc = copy.deepcopy(src)
                doc["zabbix_export"]["templates"] = [merged]
            else:
                self.next_id += 1
                tid, hosts, doc = str(self.next_id), [], copy.deepcopy(src)
                merged = doc["zabbix_export"]["templates"][0]
            self.t = {"templateid": tid, "host": merged["template"], "uuid": merged["uuid"], "description": merged["description"], "hosts": hosts, "doc": doc}
            return True
        if m == "configuration.importcompare":
            if not self.compare:
                raise RuntimeError('Incorrect method "configuration.importcompare".')
            if self.compare_error:
                raise RuntimeError(self.compare_error)
            if self.compare_override is not None:
                return self.compare_override
            src = json.loads(p["source"])
            tm = src["zabbix_export"]["templates"][0]
            if not self.t or self.t.get("uuid") != tm["uuid"]:
                return {"templates": {"added": [{"after": {"uuid": tm["uuid"], "template": tm["template"], "name": tm["name"]}}]}}
            delete = bool(p["rules"].get("items", {}).get("deleteMissing"))
            old, new = keys_of(self.doc()), keys_of(src)
            items = {"added": [{"after": {"key": k, "name": new[k]["name"]}} for k in sorted(set(new) - set(old))],
                     "removed": [{"before": {"key": k, "name": old[k]["name"]}} for k in sorted(set(old) - set(new))] if delete else [],
                     "updated": [{"before": {"key": k, "name": old[k]["name"]}, "after": {"key": k, "name": new[k]["name"]}} for k in sorted(set(old) & set(new))
                                 if _canon(old[k]) != _canon(new[k])]}
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


FakeZ = FakeTpl


def _canon(o):
    return json.dumps(o, sort_keys=True)


def keys_of(doc):
    t = doc["zabbix_export"]["templates"][0]
    ks = dict((i["key"], i) for i in t.get("items", []))
    for r in t.get("discovery_rules", []):
        for ip in r.get("item_prototypes", []):
            ks[ip["key"]] = ip
    return ks


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
        self.fz = FakeTpl()
        self.api = api_for(self.fz)

    def plan(self, d=DEF):
        return tplmgr.plan(self.api, "lab", d, self.base)

    def apply(self, d=DEF):
        return tplmgr.apply(self.api, "lab", d, self.base)

    def rollback(self, d=DEF):
        return tplmgr.rollback(self.api, "lab", d, self.base)

    def n(self, m):
        return self.fz.calls.count(m)

    def rec(self):
        return tplmgr.load_record(self.base, "lab", DEF["id"])

    def writes(self):
        return self.n("configuration.import") + self.n("template.delete")


# ===================================================================================================================== 1. ownership
class Ownership(Base):
    def test_create_records_exact_id_uuid_nonce_hashes_and_verified_baseline(self):
        r = self.apply()
        rec = self.rec()
        self.assertEqual(r["result"], "applied")
        self.assertEqual(rec["templateid"], self.fz.t["templateid"])
        self.assertEqual(rec["uuid"], UUID)
        self.assertIn("nonce=" + rec["nonce"], self.fz.t["description"])
        self.assertEqual(rec["definition_sha256"], tplmgr.definition_sha(DEF))
        self.assertEqual(rec["content_hash"], template.content_hash(DEF))
        self.assertEqual(rec["state"], "owned")
        self.assertTrue(rec["baseline"]["export_sha256"])
        self.assertEqual(rec["baseline"]["export_sha256"], tplmgr.export_live(self.api, rec["templateid"])[1])
        self.assertEqual(oct(os.stat(tplmgr.record_path(self.base, "lab", DEF["id"])).st_mode & 0o777), "0o600")
        self.assertEqual(oct(os.stat(os.path.dirname(tplmgr.record_path(self.base, "lab", DEF["id"]))).st_mode & 0o777), "0o700")

    def test_copied_marker_never_authorises_anything(self):
        self.fz.put_foreign(description=MARKER + " nonce=" + "ab" * 12)
        self.assertTrue(any("NO ownership record" in c for c in self.plan()["conflicts"]))
        with self.assertRaises(AuditError):
            self.apply()
        with self.assertRaises(AuditError):
            self.rollback()
        self.assertEqual(self.writes(), 0)

    def test_foreign_without_marker_never_adopted(self):
        self.fz.put_foreign(description="operator's own")
        with self.assertRaises(AuditError):
            self.apply()
        self.assertEqual(self.writes(), 0)

    def test_same_uuid_under_another_name_is_a_conflict(self):
        self.fz.put_foreign(host="somebody else's copy", uuid=UUID)
        self.assertTrue(any("UUID" in c for c in self.plan()["conflicts"]))
        with self.assertRaises(AuditError):
            self.apply()
        self.assertEqual(self.writes(), 0)

    def test_record_present_but_description_replaced_with_copied_marker(self):
        self.apply()
        self.fz.t["description"] = MARKER + " nonce=" + "cd" * 12
        self.assertTrue(any("nonce" in c for c in self.plan()["conflicts"]))
        n = self.writes()
        with self.assertRaises(AuditError):
            self.apply(changed_def())
        with self.assertRaises(AuditError):
            self.rollback()
        self.assertEqual(self.writes(), n)

    def test_recreated_template_with_leaked_nonce_but_other_id_is_foreign(self):
        self.apply()
        nonce = self.rec()["nonce"]
        self.fz.t = None
        self.fz.put_foreign(description=MARKER + " nonce=" + nonce)
        self.assertTrue(any("recreated or is foreign" in c for c in self.plan()["conflicts"]))
        with self.assertRaises(AuditError):
            self.apply()

    def test_same_id_but_different_uuid_fails(self):
        self.apply()
        self.fz.t["uuid"] = "9" * 32
        self.assertTrue(any("UUID" in c for c in self.plan()["conflicts"]))

    def test_renamed_template_fails(self):
        self.apply()
        self.fz.t["host"] = "renamed by operator"
        self.assertTrue(self.plan()["conflicts"])

    def test_unreadable_or_foreign_record_blocks_everything(self):
        self.apply()
        with open(tplmgr.record_path(self.base, "lab", DEF["id"]), "w") as fh:
            fh.write("{broken")
        with self.assertRaises(AuditError):
            self.plan()
        with open(tplmgr.record_path(self.base, "lab", DEF["id"]), "w") as fh:
            json.dump({"definition": "other", "env": "lab", "nonce": "x", "deployment_id": "y"}, fh)
        with self.assertRaises(AuditError):
            self.plan()

    def test_stale_record_with_nothing_live_allows_a_fresh_create_and_archives_it(self):
        self.apply()
        old = self.rec()["nonce"]
        self.fz.t = None
        self.assertEqual(self.plan()["action"], "create")
        self.apply()
        self.assertNotEqual(self.rec()["nonce"], old)
        self.assertTrue([f for f in os.listdir(os.path.dirname(tplmgr.record_path(self.base, "lab", DEF["id"]))) if "archived" in f])

    def test_production_and_disabled_writes_refused(self):
        self.assertTrue(tplmgr.plan(self.api, "production", DEF, self.base)["conflicts"])
        with self.assertRaises(AuditError):
            tplmgr.apply(api_for(self.fz, writes=False), "lab", DEF, self.base)
        for m in ("configuration.import", "template.delete"):
            with self.assertRaises(AuditError):
                api_for(self.fz, writes=False).call(m, {})
        with self.assertRaises(AuditError):
            tplmgr.apply(self.api, "lab", DEF, None)             # no state directory: ownership could not be recorded

    def test_plan_never_writes(self):
        self.apply()
        n = self.writes()
        self.plan()
        self.plan(changed_def())
        self.assertEqual(self.writes(), n)


class CreateTimeRaces(Base):
    def test_foreign_template_appearing_before_the_write_is_caught(self):
        # plan reads by name+uuid (2 template.get); the write path re-reads before importing
        self.fz.hooks[("template.get", 3)] = lambda z: z.put_foreign(description=MARKER)
        with self.assertRaises(AuditError) as cm:
            self.apply()
        self.assertIn("appeared after planning", str(cm.exception))
        self.assertEqual(self.writes(), 0)
        self.assertIsNone(self.rec())

    def test_foreign_same_name_template_created_during_the_import_fails_closed(self):
        self.fz.hooks[("configuration.import", 1)] = lambda z: z.put_foreign(description=MARKER + " nonce=" + "ee" * 12)
        with self.assertRaises(AuditError) as cm:
            self.apply()
        self.assertIn("pending record", str(cm.exception))
        self.assertEqual(self.fz.t["uuid"], "f" * 32)                  # the foreign template was not overwritten
        self.assertEqual(self.rec()["state"], "pending")
        with self.assertRaises(AuditError):
            self.rollback()
        self.assertEqual(self.n("template.delete"), 0)
        self.assertEqual(self.fz.t["uuid"], "f" * 32)

    def test_create_cannot_update_anything_that_already_exists(self):
        self.apply()
        self.assertEqual(self.fz.import_rules[0], template.CREATE_RULES)
        self.assertFalse(template.CREATE_RULES["templates"]["updateExisting"])

    def test_import_that_loses_the_nonce_is_not_treated_as_owned(self):
        orig = self.fz.handle

        def lose(m, p):
            r = orig(m, p)
            if m == "configuration.import":
                self.fz.t["description"] = self.fz.t["description"].replace("nonce=", "nonce=00")
            return r
        self.fz.handle = lose
        with self.assertRaises(AuditError):
            self.apply()
        self.assertEqual(self.rec()["state"], "pending")
        with self.assertRaises(AuditError):
            self.rollback()
        self.assertEqual(self.n("template.delete"), 0)

    def test_imported_content_that_differs_from_the_intent_is_not_a_baseline(self):
        orig = self.fz.handle

        def extra(m, p):
            r = orig(m, p)
            if m == "configuration.import":
                self.fz.tm().setdefault("items", []).append({"uuid": "b" * 32, "name": "x", "key": "x", "type": "TRAP"})
            return r
        self.fz.handle = extra
        with self.assertRaises(AuditError):
            self.apply()
        rec = self.rec()
        self.assertEqual(rec["state"], "pending")
        self.assertIsNone(rec["baseline"])


# ===================================================================================================================== 2. drift
class Drift(Base):
    MUTATIONS = {
        "added item": lambda z: z.gui_edit(),
        "removed item": lambda z: z.tm()["items"].pop(),
        "changed item field": lambda z: z.edit_first("items", "delay", "10s"),
        "changed macro": lambda z: z.edit_first("macros", "value", "99h"),
        "added macro": lambda z: z.tm()["macros"].append({"macro": "{$OPERATOR}", "value": "1"}),
        "changed valuemap": lambda z: z.tm()["valuemaps"][0]["mappings"].append({"value": "99", "newvalue": "hacked"}),
        "added discovery rule": lambda z: z.tm()["discovery_rules"].append({"uuid": "c" * 32, "name": "extra", "key": "operator.rule", "type": "TRAP"}),
        "changed preprocessing": lambda z: z.tm()["discovery_rules"][0]["item_prototypes"][0].__setitem__("preprocessing", [{"type": "NOT_SUPPORTED", "parameters": []}]),
        "changed trigger prototype expression": lambda z: z.tm()["discovery_rules"][0]["item_prototypes"][0]["trigger_prototypes"][0].__setitem__("expression", "1=1"),
        "changed description text": lambda z: z.tm().__setitem__("description", z.tm()["description"] + " edited"),
    }

    def test_every_kind_of_manual_change_is_drift_not_noop(self):
        for label, mutate in self.MUTATIONS.items():
            self.setUp()
            self.apply()
            self.assertEqual(self.plan()["action"], "noop", label)
            mutate(self.fz)
            self.fz.t["description"] = self.fz.tm()["description"]
            p = self.plan()
            self.assertNotEqual(p["action"], "noop", label)
            self.assertTrue(any("DRIFT" in c for c in p["conflicts"]), (label, p["conflicts"]))
            self.assertTrue(p["drift"], label)
            n = self.writes()
            for fn in (self.apply, self.rollback):
                with self.assertRaises(AuditError):
                    fn()
            self.assertEqual(self.writes(), n, label)

    def test_drift_report_names_the_exact_objects(self):
        self.apply()
        self.fz.gui_edit()
        self.fz.edit_first("macros", "value", "42m")
        p = self.plan()
        self.assertIn("ADDED item:operator.added", p["drift"])
        self.assertTrue(any(x.startswith("CHANGED macro:") for x in p["drift"]))

    def test_unchanged_description_hash_is_not_enough_for_noop(self):
        self.apply()
        d_before = self.fz.t["description"]
        self.fz.gui_edit()
        self.assertEqual(self.fz.t["description"], d_before)
        self.assertNotEqual(self.plan()["action"], "noop")

    def test_noop_is_decided_from_the_real_export(self):
        self.apply()
        n = self.n("configuration.export")
        self.assertEqual(self.plan()["action"], "noop")
        self.assertGreater(self.n("configuration.export"), n)

    def test_there_is_no_override_flag(self):
        import hardware_audit
        for flag in ("--accept-drift", "--approve-linked-update", "--approve-removals"):
            with self.assertRaises(SystemExit):
                hardware_audit._parser().parse_args(["--env", "lab", "template", "apply", "--definition", "cisco-iosxe", flag, "REF-1"])

    def test_change_between_plan_and_write_is_caught(self):
        self.apply()
        n = self.fz.count.get("configuration.export", 0)
        # plan: drift export (#1); write path: ownership export (#2) -> edit just before it
        self.fz.hooks[("configuration.export", n + 2)] = lambda z: z.gui_edit()
        w = self.writes()
        with self.assertRaises(AuditError) as cm:
            self.apply(changed_def())
        self.assertIn("REFUSED at the write", str(cm.exception))
        self.assertEqual(self.writes(), w)

    def test_change_while_backing_up_is_caught_before_any_import(self):
        self.apply()
        n = self.fz.count.get("configuration.export", 0)
        # plan #1, ownership+backup #2, final fresh ownership export #3: edit right before it
        self.fz.hooks[("configuration.export", n + 3)] = lambda z: z.gui_edit()
        w = self.writes()
        with self.assertRaises(AuditError) as cm:
            self.apply(changed_def())
        self.assertIn("REFUSED at the write", str(cm.exception))
        self.assertEqual(self.writes(), w)


# ===================================================================================================================== 3. rollback
class RollbackOwnership(Base):
    def test_rollback_of_a_create_deletes_exactly_the_recorded_id(self):
        self.apply()
        tid = self.fz.t["templateid"]
        r = self.rollback()
        self.assertEqual((r["result"], r["templateid"]), ("deleted", tid))
        self.assertIsNone(self.fz.t)
        self.assertIsNone(self.rec())

    def test_recreated_same_name_template_with_copied_marker_and_nonce_is_never_deleted(self):
        self.apply()
        nonce = self.rec()["nonce"]
        original = self.fz.t["templateid"]
        self.fz.t = None
        self.fz.put_foreign(description=MARKER + " nonce=" + nonce)
        self.assertNotEqual(self.fz.t["templateid"], original)
        r = self.rollback()
        self.assertEqual(r["result"], "already-absent")
        self.assertIn("NOT touched", r["note"])
        self.assertEqual(self.n("template.delete"), 0)
        self.assertIsNotNone(self.fz.t)

    def test_the_delete_call_carries_only_the_recorded_id(self):
        sent = []
        self.apply()
        tid = self.fz.t["templateid"]
        orig = self.fz.handle
        self.fz.handle = lambda m, p: (sent.append(p) if m == "template.delete" else None) or orig(m, p)
        self.rollback()
        self.assertEqual(sent, [[tid]])

    def test_template_replaced_between_checks_and_delete_is_not_deleted(self):
        self.apply()
        n = self.fz.count.get("template.get", 0)
        nonce = self.rec()["nonce"]
        self.fz.hooks[("template.get", n + 3)] = lambda z: (setattr(z, "t", None), z.put_foreign(description=MARKER + " nonce=" + nonce))
        try:
            self.rollback()
        except AuditError:
            pass
        self.assertEqual(self.n("template.delete"), 0)
        self.assertEqual(self.fz.t["uuid"], "f" * 32)

    def test_backups_record_exact_id_and_binding(self):
        self.apply()
        rec = self.rec()
        step = rec["steps"][0]
        for key, kind in (("intent", "create-intent"), ("created", "create")):
            bk = tplmgr.read_verified(step[key], step[key + "_sha256"])
            self.assertEqual((bk["deployment_id"], bk["nonce"], bk["kind"], bk["op_id"], bk["env"], bk["definition"]), (rec["deployment_id"], rec["nonce"], kind, step["op_id"], "lab", DEF["id"]))
        self.assertEqual(tplmgr.read_verified(step["created"], step["created_sha256"])["templateid"], rec["templateid"])

    def test_backup_from_another_deployment_is_refused(self):
        self.apply()
        old_step = self.rec()["steps"][0]
        self.rollback()                                           # deleted; a second, different deployment follows
        self.apply()
        rec = self.rec()
        rec["steps"][0].update(created=old_step["created"], created_sha256=old_step["created_sha256"])
        tplmgr.save_record(self.base, "lab", DEF["id"], rec)
        with self.assertRaises(AuditError) as cm:
            self.rollback()
        self.assertIn("not bound to this deployment", str(cm.exception))
        self.assertEqual(self.n("template.delete"), 1)            # only the first, legitimate rollback

    def test_modified_or_missing_backup_is_refused(self):
        self.apply()
        step = self.rec()["steps"][0]
        os.chmod(step["created"], 0o600)
        with open(step["created"], "a") as fh:
            fh.write(" ")
        with self.assertRaises(AuditError) as cm:
            self.rollback()
        self.assertIn("SHA-256", str(cm.exception))
        os.remove(step["created"])
        with self.assertRaises(AuditError):
            self.rollback()
        self.assertEqual(self.n("template.delete"), 0)

    def test_rollback_without_a_record_never_selects_by_name(self):
        self.fz.put_foreign(description=MARKER)
        with self.assertRaises(AuditError):
            tplmgr.rollback(self.api, "lab", NAME, self.base)       # a template NAME is accepted only to find the definition
        self.assertEqual(self.n("template.delete"), 0)


class InterruptedOperations(Base):
    def test_failure_before_the_import_leaves_nothing_and_recovers(self):
        self.fz.compare_error = "boom"
        with self.assertRaises(AuditError):
            self.apply()
        self.assertEqual(self.writes(), 0)
        self.assertIsNone(self.rec())

    def test_import_error_leaves_a_pending_record_that_recovers_to_nothing(self):
        self.fz.fail_import = "database connection lost"
        with self.assertRaises(AuditError) as cm:
            self.apply()
        self.assertIn("pending record", str(cm.exception))
        self.assertEqual(self.rec()["state"], "pending")
        self.assertIn("interrupted operation", " ".join(self.plan()["conflicts"]))
        r = self.rollback()
        self.assertEqual(r["result"], "nothing-to-roll-back")
        self.assertIsNone(self.rec())
        self.assertEqual(self.n("template.delete"), 0)

    def test_interrupted_creation_is_recovered_only_when_nonce_uuid_and_content_match(self):
        orig = self.fz.handle
        state = {"boom": True}

        def crash_after_import(m, p):
            if m == "template.get" and p.get("filter", {}).get("host") and self.fz.count.get("configuration.import") and state["boom"]:
                state["boom"] = False
                raise KeyError("process died after the import")
            return orig(m, p)
        self.fz.handle = crash_after_import
        with self.assertRaises(AuditError):
            self.apply()
        self.fz.handle = orig
        self.assertEqual(self.rec()["state"], "pending")
        tid = self.fz.t["templateid"]
        r = self.rollback()
        self.assertEqual((r["result"], r["templateid"]), ("deleted", tid))

    def test_interrupted_creation_with_a_replaced_template_is_refused(self):
        self.fz.fail_import = "x"
        with self.assertRaises(AuditError):
            self.apply()
        self.fz.fail_import = None
        self.fz.put_foreign(description=MARKER)                    # something with the same name appears meanwhile
        with self.assertRaises(AuditError) as cm:
            self.rollback()
        self.assertIn("NOT touched", str(cm.exception))
        self.assertEqual(self.n("template.delete"), 0)

    def test_interrupted_creation_with_copied_nonce_but_other_content_is_refused(self):
        self.fz.fail_import = "x"
        with self.assertRaises(AuditError):
            self.apply()
        nonce = self.rec()["nonce"]
        self.fz.fail_import = None
        self.fz.put_foreign(uuid=UUID, description=MARKER + " nonce=" + nonce)     # same uuid and nonce, but not the intended content
        with self.assertRaises(AuditError):
            self.rollback()
        self.assertEqual(self.n("template.delete"), 0)

    def test_interrupted_update_before_the_import_is_discarded(self):
        self.apply()
        self.fz.fail_import = "lost"
        with self.assertRaises(AuditError):
            self.apply(changed_def())
        self.fz.fail_import = None
        rec = self.rec()
        self.assertEqual(rec["steps"][-1]["state"], "pending")
        self.assertIn("interrupted operation", " ".join(self.plan(changed_def())["conflicts"]))
        r = self.rollback()
        self.assertEqual(r["result"], "interrupted-update-discarded")
        self.assertEqual(len(self.rec()["steps"]), 1)
        self.assertEqual(self.plan()["action"], "noop")

    def test_interrupted_update_after_the_import_with_a_recorded_post_hash_is_restorable(self):
        self.apply()
        _, before, _ = tplmgr.export_live(self.api, self.fz.t["templateid"])
        orig = self.fz.handle

        def lossy(m, p):
            r = orig(m, p)
            if m == "configuration.import" and self.fz.count["configuration.import"] == 2:
                self.fz.tm().setdefault("items", []).append({"uuid": "d" * 32, "name": "junk", "key": "junk", "type": "TRAP"})
            return r
        self.fz.handle = lossy
        with self.assertRaises(AuditError):
            self.apply(changed_def())                                # post-import verification fails: the step stays pending WITH a post hash
        self.fz.handle = orig
        self.assertTrue(self.rec()["steps"][-1].get("post_export_sha256"))
        r = self.rollback()
        self.assertEqual(r["result"], "restored")
        self.assertEqual(tplmgr.export_live(self.api, self.fz.t["templateid"])[1], before)

    def test_interrupted_update_after_the_import_without_a_post_hash_is_refused(self):
        self.apply()
        orig = self.fz.handle
        state = {"done": False}

        def die(m, p):
            if m == "template.get" and p.get("templateids") and self.fz.count.get("configuration.import", 0) == 2 and not state["done"]:
                state["done"] = True
                raise KeyError("died right after the import")
            return orig(m, p)
        self.fz.handle = die
        with self.assertRaises(AuditError):
            self.apply(changed_def())
        self.fz.handle = orig
        w = self.writes()
        with self.assertRaises(AuditError):
            self.rollback()
        self.assertEqual(self.writes(), w)


# ===================================================================================================================== 4. linked templates
class LinkedTemplates(Base):
    def test_plan_lists_linked_hosts_and_refuses_the_update_without_any_override(self):
        self.apply()
        self.fz.link()
        p = self.plan(changed_def())
        self.assertEqual((p["linked_hosts"], p["linked_host_ids"]), (1, ["77"]))
        self.assertTrue(any("linked to 1 host(s) (ids 77)" in c for c in p["conflicts"]))
        w = self.writes()
        with self.assertRaises(AuditError):
            self.apply(changed_def())
        self.assertEqual(self.writes(), w)

    def test_a_linked_but_current_template_is_simply_noop(self):
        self.apply()
        self.fz.link()
        p = self.plan()
        self.assertEqual((p["action"], p["linked_host_ids"]), ("noop", ["77"]))

    def test_link_appearing_after_planning_is_caught_at_the_write(self):
        self.apply()
        n = self.fz.count.get("configuration.export", 0)
        self.fz.hooks[("configuration.export", n + 3)] = lambda z: z.link()
        w = self.writes()
        with self.assertRaises(AuditError) as cm:
            self.apply(changed_def())
        self.assertIn("linked", str(cm.exception))
        self.assertEqual(self.writes(), w)

    def test_rollback_of_a_linked_create_is_refused(self):
        self.apply()
        self.fz.link()
        with self.assertRaises(AuditError) as cm:
            self.rollback()
        self.assertIn("linked", str(cm.exception))
        self.assertEqual(self.n("template.delete"), 0)
        self.assertIsNotNone(self.fz.t)

    def test_rollback_of_a_linked_update_is_refused(self):
        self.apply()
        self.apply(changed_def())
        self.fz.link()
        w = self.writes()
        with self.assertRaises(AuditError):
            self.rollback()
        self.assertEqual(self.writes(), w)

    def test_hosts_are_never_unlinked(self):
        self.apply()
        self.fz.link()
        for fn in (lambda: self.apply(changed_def()), self.rollback):
            try:
                fn()
            except AuditError:
                pass
        self.assertEqual(self.fz.t["hosts"], [{"hostid": "77", "host": "linked-host"}])
        for m in self.fz.calls:
            self.assertNotIn(m, ("host.update", "host.massremove", "template.massremove", "template.update"))


# ===================================================================================================================== 5. non-destructive import
class NonDestructiveImport(Base):
    def test_default_rules_never_contain_delete_missing(self):
        for rules in (template.IMPORT_RULES, template.CREATE_RULES):
            for k, v in rules.items():
                self.assertFalse(v.get("deleteMissing", False), k)
        for k in ("valueMaps", "discoveryRules", "items", "triggers"):
            self.assertIn("deleteMissing", template.IMPORT_RULES[k])             # spelled out, not omitted
            self.assertIs(template.IMPORT_RULES[k]["deleteMissing"], False)
        self.assertFalse(template.CREATE_RULES["templates"]["updateExisting"])
        self.assertTrue(template.RESTORE_RULES["items"]["deleteMissing"])        # reachable only from rollback

    def test_apply_sends_exactly_the_safe_rules(self):
        self.apply()
        self.apply(changed_def())
        self.assertEqual(self.fz.import_rules, [template.CREATE_RULES, template.IMPORT_RULES])

    def test_update_never_deletes_children_that_exist_live(self):
        self.apply()
        full = len(keys_of(self.fz.doc()))
        p = self.plan(reduced_def())
        self.assertEqual(p["action"], "update")
        self.assertTrue(p["compare"]["obsolete_left_in_place"])
        self.apply(reduced_def())
        self.assertEqual(len(keys_of(self.fz.doc())), full)                       # nothing was deleted
        self.assertEqual(self.plan(reduced_def())["action"], "noop")

    def test_importcompare_is_mandatory_for_create_and_update(self):
        fz = FakeTpl(compare=False)
        self.fz, self.api = fz, api_for(fz)
        self.assertTrue(any("not available" in c for c in self.plan()["conflicts"]))
        with self.assertRaises(AuditError):
            self.apply()
        self.assertEqual(self.writes(), 0)

    def test_importcompare_rejection_is_a_conflict(self):
        self.fz.compare_error = "Invalid parameter \"/1/source\": unexpected tag."
        self.assertTrue(any("rejected" in c for c in self.plan()["conflicts"]))
        with self.assertRaises(AuditError):
            self.apply()
        self.assertEqual(self.writes(), 0)

    def test_any_reported_deletion_blocks_the_import(self):
        self.apply()
        entry = {"before": {"uuid": "u", "template": NAME, "name": NAME}, "after": {"uuid": "u", "template": NAME, "name": NAME},
                 "items": {"removed": [{"before": {"key": "k", "name": "n"}}]}}
        self.fz.compare_override = {"templates": {"updated": [entry]}}
        p = self.plan(changed_def())
        self.assertTrue(any("DELETED" in c for c in p["conflicts"]))
        w = self.writes()
        with self.assertRaises(AuditError):
            self.apply(changed_def())
        self.assertEqual(self.writes(), w)

    def test_unexpected_operations_block_the_import(self):
        self.fz.compare_override = {"templates": {"updated": [{"before": {"template": NAME}, "after": {"template": NAME}}]}}
        self.assertTrue(any("must only add" in c or "exactly one template being created" in c for c in self.plan()["conflicts"]))
        self.fz.compare_override = {"templates": {"added": [{"after": {"template": NAME}}]}, "host_groups": {"updated": [{"before": {"name": "Linux"}, "after": {"name": "Linux"}}]}}
        self.assertTrue(any("outside the template" in c for c in self.plan()["conflicts"]))
        self.fz.compare_override = {"templates": {"added": [{"after": {"template": "another"}}]}}
        self.assertTrue(self.plan()["conflicts"])

    def test_rename_and_template_removal_are_refused(self):
        e = {"before": {"template": NAME}, "after": {"template": "other"}}
        probs = tplmgr.judge_compare([{"op": "updated", "path": "templates", "label": "other", "entry": e}], "update", NAME)
        self.assertTrue(any("other than" in p or "RENAME" in p for p in probs))
        probs = tplmgr.judge_compare([{"op": "removed", "path": "templates", "label": NAME, "entry": {"before": {"template": NAME}}}], "update", NAME)
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
        self.assertEqual(sorted((o["op"], o["path"], o["label"]) for o in ops), sorted([
            ("updated", "templates", "New template"), ("added", "templates/items", "CPU utilization (system.cpu.util)"),
            ("added", "templates/items/triggers", "CPU utilization too high"), ("removed", "templates/items", "CPU load (system.cpu.load)"),
            ("removed", "templates/items/triggers", "CPU load too high"), ("updated", "templates/items", "Zabbix agent ping (agent.ping)")]))
        self.assertTrue(any("2 object(s) would be DELETED" in p for p in tplmgr.judge_compare(ops, "update", "New template")))


# ===================================================================================================================== backups / restore
class ImmutableBackups(Base):
    def test_every_update_writes_a_new_immutable_backup_and_keeps_the_old_ones(self):
        self.apply()
        a = self.apply(changed_def())["backup"]
        d2 = changed_def()
        d2["sensors"][0]["triggers"][0]["recover_samples"] = 4
        b = self.apply(d2)["backup"]
        self.assertNotEqual(a, b)
        self.assertTrue(os.path.isfile(a) and os.path.isfile(b))
        for path in (a, b):
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode) & 0o222, 0)       # read-only
        files = os.listdir(os.path.dirname(a))
        self.assertEqual(len(set(files)), len(files))
        self.assertTrue(all(("-update.json" in f or "-create" in f) for f in files))

    def test_write_immutable_refuses_to_overwrite(self):
        path = os.path.join(self.base, "x.json")
        tplmgr.write_immutable(path, {"a": 1})
        with self.assertRaises(AuditError):
            tplmgr.write_immutable(path, {"a": 2})
        with open(path) as fh:
            self.assertEqual(json.load(fh), {"a": 1})

    def test_rollback_walks_back_one_operation_at_a_time(self):
        self.apply()
        _, s0, _ = tplmgr.export_live(self.api, self.fz.t["templateid"])
        self.apply(changed_def())
        _, s1, _ = tplmgr.export_live(self.api, self.fz.t["templateid"])
        d2 = changed_def()
        d2["sensors"][0]["triggers"][0]["recover_samples"] = 4
        self.apply(d2)
        self.assertEqual(self.rollback()["result"], "restored")
        self.assertEqual(tplmgr.export_live(self.api, self.fz.t["templateid"])[1], s1)
        self.assertEqual(self.rollback()["result"], "restored")
        self.assertEqual(tplmgr.export_live(self.api, self.fz.t["templateid"])[1], s0)
        self.assertEqual(self.rollback()["result"], "deleted")

    def test_restore_removes_only_what_the_update_added(self):
        self.apply(reduced_def())
        self.apply(DEF)                                            # the full definition adds the last sensor
        added = self.rollback()
        self.assertEqual(added["result"], "restored")
        self.assertTrue(added["removed_objects"])
        self.assertTrue(all(x.split(":")[0] in ("item", "rule", "item_prototype", "trigger", "trigger_prototype", "valuemap", "macro") for x in added["removed_objects"]))

    def test_restore_that_does_not_reproduce_the_original_is_reported(self):
        self.apply()
        self.apply(changed_def())
        orig = self.fz.handle

        def lossy(m, p):
            r = orig(m, p)
            if m == "configuration.import" and self.fz.count["configuration.import"] == 3:
                self.fz.tm().setdefault("items", []).append({"uuid": "e" * 32, "name": "x", "key": "x", "type": "TRAP"})
            return r
        self.fz.handle = lossy
        with self.assertRaises(AuditError) as cm:
            self.rollback()
        self.assertIn("does not reproduce", str(cm.exception))

    def test_deleted_backup_blocks_the_restore(self):
        self.apply()
        r = self.apply(changed_def())
        os.chmod(r["backup"], 0o600)
        os.remove(r["backup"])
        w = self.writes()
        with self.assertRaises(AuditError):
            self.rollback()
        self.assertEqual(self.writes(), w)

    def test_restore_removal_budget_is_bounded(self):
        probs = tplmgr.judge_compare([{"op": "removed", "path": "templates/items", "label": "a", "entry": {}}, {"op": "removed", "path": "templates/items", "label": "b", "entry": {}}],
                                     "restore", NAME, allow_removed=1)
        self.assertTrue(any("only 1 were added" in p for p in probs))


class InventoryHelpers(unittest.TestCase):
    def test_inventory_attributes_a_change_to_the_exact_object(self):
        doc = template.build(DEF)
        a = tplmgr.inventory(doc)
        doc2 = copy.deepcopy(doc)
        doc2["zabbix_export"]["templates"][0]["discovery_rules"][0]["item_prototypes"][0]["delay"] = "9s"
        b = tplmgr.inventory(doc2)
        dd = tplmgr.diff_inventory(a, b)
        self.assertEqual(len(dd), 1)
        self.assertTrue(dd[0].startswith("CHANGED item_prototype:"))

    def test_generated_identity_covers_every_object_kind(self):
        ids = tplmgr.identity(template.build(DEF))
        for kind in ("item:", "trigger:", "rule:", "item_prototype:", "trigger_prototype:", "valuemap:", "macro:"):
            self.assertTrue(any(i.startswith(kind) for i in ids), kind)

    def test_normalize_export_drops_only_the_date(self):
        c1 = tplmgr.normalize_export(json.dumps({"zabbix_export": {"date": "x", "templates": [{"template": "t"}]}}))
        c2 = tplmgr.normalize_export(json.dumps({"zabbix_export": {"templates": [{"template": "t"}], "date": "y"}}))
        self.assertEqual(c1[1], c2[1])
        with self.assertRaises(AuditError):
            tplmgr.normalize_export("not json")


if __name__ == "__main__":
    unittest.main()

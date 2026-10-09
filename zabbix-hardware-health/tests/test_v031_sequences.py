"""Combined sequences: races, replacement, drift and partial failures chained together (v0.3.1)."""
import os
import unittest

from hwh import template, tplmgr
from hwh.api import AuditError
from tests.test_v03_tplmgr import DEF, MARKER, NAME, UUID, Base, FakeTpl, changed_def


class Sequences(Base):
    def test_delete_and_recreate_an_identical_copy_with_the_same_uuid_marker_and_nonce(self):
        """An operator exports our template, deletes it and re-imports the copy: same name, UUID, marker and nonce - but not our id."""
        self.apply()
        rec = self.rec()
        doc = self.fz.doc()
        self.fz.t = None
        self.fz.put_foreign(uuid=UUID, description=self.fz_desc(doc), doc=doc)
        self.assertNotEqual(self.fz.t["templateid"], rec["templateid"])
        self.assertTrue(any("recreated or is foreign" in c for c in self.plan(changed_def())["conflicts"]))
        w = self.writes()
        for fn in (lambda: self.apply(changed_def()), self.rollback):
            try:
                fn()
            except AuditError:
                pass
        self.assertEqual(self.writes(), w)

    @staticmethod
    def fz_desc(doc):
        return doc["zabbix_export"]["templates"][0]["description"]

    def test_drift_blocks_everything_and_reverting_it_by_hand_unblocks(self):
        self.apply()
        self.apply(changed_def())
        self.fz.gui_edit()
        self.assertTrue(any("DRIFT" in c for c in self.plan(changed_def())["conflicts"]))
        w = self.writes()
        with self.assertRaises(AuditError):
            self.apply(changed_def())
        with self.assertRaises(AuditError):
            self.rollback()
        self.assertEqual(self.writes(), w)
        self.fz.tm()["items"] = [i for i in self.fz.tm()["items"] if i["key"] != "operator.added"]       # the operator removes their own change again
        self.assertEqual(self.plan(changed_def())["action"], "noop")
        self.assertEqual(self.rollback()["result"], "restored")

    def test_failed_update_then_drift_then_recovery(self):
        self.apply()
        self.fz.fail_import = "lost connection"
        with self.assertRaises(AuditError):
            self.apply(changed_def())
        self.fz.fail_import = None
        self.assertIn("interrupted operation", " ".join(self.plan(changed_def())["conflicts"]))
        self.fz.gui_edit()                                       # while the operation is unresolved somebody edits the template
        w = self.writes()
        with self.assertRaises(AuditError):
            self.rollback()                                      # live matches neither the pre-update nor a recorded post-update export
        self.assertEqual(self.writes(), w)
        self.fz.tm()["items"] = [i for i in self.fz.tm()["items"] if i["key"] != "operator.added"]
        self.assertEqual(self.rollback()["result"], "interrupted-update-discarded")
        self.assertEqual(self.plan()["action"], "noop")
        self.assertEqual(self.apply(changed_def())["result"], "applied")

    def test_race_during_create_then_operator_cleans_up_then_retry_succeeds(self):
        self.fz.hooks[("configuration.import", 1)] = lambda z: z.put_foreign(description=MARKER)
        with self.assertRaises(AuditError):
            self.apply()
        with self.assertRaises(AuditError):
            self.rollback()                                      # the foreign template is not ours
        self.assertEqual(self.n("template.delete"), 0)
        self.fz.t = None                                         # the operator removes THEIR template themselves
        self.assertEqual(self.rollback()["result"], "nothing-to-roll-back")
        self.assertEqual(self.apply()["result"], "applied")
        self.assertEqual(self.plan()["action"], "noop")

    def test_linked_and_drifted_template_is_never_touched(self):
        self.apply()
        self.fz.link()
        self.fz.gui_edit()
        w = self.writes()
        for fn in (lambda: self.apply(changed_def()), self.rollback):
            with self.assertRaises(AuditError):
                fn()
        self.assertEqual(self.writes(), w)
        self.assertEqual(self.fz.t["hosts"], [{"hostid": "77", "host": "linked-host"}])

    def test_stale_record_and_a_foreign_same_name_template(self):
        self.apply()
        self.fz.t = None
        self.fz.put_foreign(description="mine now")
        self.assertTrue(self.plan()["conflicts"])
        for fn in (self.apply, self.rollback):
            try:
                fn()
            except AuditError:
                pass
        self.assertEqual(self.writes(), 1)                        # only the original create import
        self.assertEqual(self.fz.t["description"], "mine now")

    def test_rollback_never_removes_backup_files_and_the_audit_trail_grows(self):
        self.apply()
        r1 = self.apply(changed_def())
        files_before = set(os.listdir(os.path.join(self.base, "state", "backups")))
        self.rollback()
        self.rollback()
        files_after = set(os.listdir(os.path.join(self.base, "state", "backups")))
        self.assertTrue(files_before <= files_after)
        self.assertTrue(os.path.isfile(r1["backup"]))

    def test_second_apply_after_rollback_creates_a_new_deployment_identity(self):
        self.apply()
        first = self.rec()
        self.rollback()
        self.apply()
        second = self.rec()
        self.assertNotEqual((first["nonce"], first["deployment_id"]), (second["nonce"], second["deployment_id"]))
        self.assertNotEqual(first["templateid"], second["templateid"])

    def test_every_writing_call_is_preceded_by_a_fresh_ownership_read(self):
        self.apply()
        self.apply(changed_def())
        self.rollback()
        calls = self.fz.calls
        for i, m in enumerate(calls):
            if m == "template.delete" or (m == "configuration.import" and i > calls.index("configuration.import")):
                window = calls[max(0, i - 4):i]
                self.assertIn("template.get", window)
                self.assertIn("configuration.export", calls[max(0, i - 8):i])


if __name__ == "__main__":
    unittest.main()

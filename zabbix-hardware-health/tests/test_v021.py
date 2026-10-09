"""v0.2.1: documented EVENT.TAGS macro syntax, separate coverage dimensions, raw-input subset count, missing/unreachable/stale clarity, explicit recipients."""
import re
import unittest

from hwh import action as A
from hwh import audit as AU
from hwh.api import AuditError, ZabbixAPI
from tests.fakes import NOW, FakeZabbix
from tests.helpers import Project, ROOT, TAGS_FAN, audit_host, cisco_policy, fan_sensor, good_fake


class TestMessageMacros(unittest.TestCase):
    ALL = A.SUBJECT + A.MESSAGE + A.R_SUBJECT + A.R_MESSAGE

    def test_tag_macro_uses_the_quoted_documented_form(self):
        self.assertEqual(A.tag_macro("hardware_model"), '{EVENT.TAGS."hardware_model"}')

    def test_quote_and_backslash_in_a_tag_name_are_escaped(self):
        self.assertEqual(A.tag_macro('a"b'), '{EVENT.TAGS."a\\"b"}')
        self.assertEqual(A.tag_macro("a\\b"), '{EVENT.TAGS."a\\\\b"}')

    def test_invalid_names_are_refused(self):
        for bad in ("", "x\ny"):
            with self.assertRaises(AuditError):
                A.tag_macro(bad)

    def test_no_unquoted_underscore_tag_macro_remains(self):
        self.assertIsNone(re.search(r"\{EVENT\.TAGS\.[A-Za-z]", self.ALL), "an unquoted {EVENT.TAGS.name} macro is still in a template")

    def test_every_payload_tag_is_present_and_quoted_in_problem_and_recovery_text(self):
        for tag in A.PAYLOAD_TAGS:
            m = '{EVENT.TAGS."%s"}' % tag
            self.assertIn(m, A.MESSAGE, tag)
            self.assertIn(m, A.R_MESSAGE, tag)

    def test_payload_carries_every_required_field(self):
        for token in ("{HOST.NAME}", "{EVENT.SEVERITY}", "{EVENT.DATE}", "{EVENT.TIME}", "{EVENT.ID}", "{EVENT.STATUS}", "{EVENT.NAME}"):
            self.assertIn(token, A.MESSAGE + A.SUBJECT)
        self.assertIn("{EVENT.RECOVERY.DATE}", A.R_MESSAGE)
        self.assertIn("{EVENT.DURATION}", A.R_MESSAGE)

    def test_only_documented_macro_families_are_used(self):
        names = set(n.rstrip(".") for n in re.findall(r"{([A-Z][A-Z.]*)", self.ALL))
        self.assertTrue(names <= {"EVENT.STATUS", "EVENT.NAME", "HOST.NAME", "EVENT.SEVERITY", "EVENT.TAGS", "EVENT.DATE", "EVENT.TIME", "EVENT.ID",
                                  "EVENT.RECOVERY.DATE", "EVENT.RECOVERY.TIME", "EVENT.DURATION"}, names)
        self.assertNotIn("INVENTORY", self.ALL)          # LAB hosts have empty inventory: the model comes from the policy-driven hardware_model tag

    def test_macros_are_what_the_created_action_carries(self):
        p = A.build_params("3", ["7"], enabled=False)
        self.assertEqual(p["operations"][0]["opmessage"]["message"], A.MESSAGE)
        self.assertEqual(p["recovery_operations"][0]["opmessage"]["message"], A.R_MESSAGE)
        self.assertEqual(p["status"], 1)


class TestSeparateDimensions(unittest.TestCase):
    def test_reads_fine_but_no_trigger_is_telemetry_pass_alert_gap(self):
        fz, hid, iid = good_fake()
        fz.triggers[hid] = []
        h = audit_host(fz, cisco_policy([fan_sensor()]))
        s = h["categories"]["fan"]["sensors"][0]
        self.assertEqual((s["telemetry_coverage"], s["alert_coverage"]), (AU.PASS, AU.GAP))
        self.assertEqual((h["telemetry_coverage"], h["alert_coverage"], h["verdict"]), (AU.PASS, AU.GAP, AU.GAP))
        self.assertEqual(s["current_state"], "normal")                 # the value is kept: the sensor is not "absent"

    def test_fully_covered_is_pass_pass(self):
        fz, hid, iid = good_fake()
        h = audit_host(fz, cisco_policy([fan_sensor()]))
        self.assertEqual((h["telemetry_coverage"], h["alert_coverage"], h["verdict"]), (AU.PASS, AU.PASS, AU.PASS))

    def test_unreadable_sensor_leaves_alert_coverage_not_evaluated(self):
        fz, hid, iid = good_fake(lastclock=0)
        h = audit_host(fz, cisco_policy([fan_sensor()]))
        s = h["categories"]["fan"]["sensors"][0]
        self.assertEqual((s["telemetry_coverage"], s["alert_coverage"]), (AU.GAP, AU.NOT_EVALUATED))
        self.assertEqual(h["alert_coverage"], AU.NOT_EVALUATED)

    def test_no_declared_sensor(self):
        fz, hid, iid = good_fake()
        h = audit_host(fz, cisco_policy([], expected=("fan",)))
        c = h["categories"]["fan"]
        self.assertEqual((c["telemetry_coverage"], c["alert_coverage"]), (AU.GAP, AU.NOT_EVALUATED))

    def test_na_category_is_na_in_both_dimensions(self):
        fz, hid, iid = good_fake()
        h = audit_host(fz, cisco_policy([fan_sensor()], not_applicable={"hw_redundancy": {"evidence": "fixed single supply per DS-1"}}))
        c = h["categories"]["hw_redundancy"]
        self.assertEqual((c["telemetry_coverage"], c["alert_coverage"], c["verdict"]), (AU.NA, AU.NA, AU.NA))
        self.assertEqual(h["verdict"], AU.PASS)

    def test_report_has_per_dimension_summaries_and_readiness(self):
        fz, hid, iid = good_fake()
        p = Project(hosts_yaml="""hosts:
  NX-01:
    site: SITE-A
    vendor: cisco
    family: cisco-nxos
    model: TEST-MODEL-1
    expected: [fan]
    sensors:
      - {category: fan, key: "sensor.fan.status[1]", semantics: test-status}
""", semantics_yaml='semantics:\n  test-status:\n    vendor: cisco\n    evidence: "synthetic test fixture - not vendor data"\n    verified: true\n    states: {"10": normal}\n', fake=fz)
        try:
            import json
            rc, out, err = p.run("--env", "lab", "audit")
            rep = json.loads(out)
            self.assertEqual(rep["schema"], 3)
            self.assertEqual(rep["telemetry_summary"], {"PASS": 1})
            self.assertEqual(rep["alert_summary"], {"PASS": 1})
            r = rep["notification_readiness"]
            self.assertEqual(r["state"], "NOT_READY")                  # strong telemetry and alert coverage do NOT imply notification readiness
            self.assertFalse(r["delivery_tested"])
            self.assertTrue(any("does not exist" in x for x in r["reasons"]))
            self.assertTrue(any("not validated" in x for x in r["reasons"]))
            self.assertEqual(fz.writes(), [])
        finally:
            p.close()

    def test_readiness_never_validated_without_all_evidence(self):
        fz = FakeZabbix()
        api = ZabbixAPI("https://f.example", "t", transport=fz)
        fz.add_action(A.ACTION_NAME, A.hardware_filter(), status="0")      # exists and enabled, but nothing validated
        r = A.readiness(api, str(ROOT / "config" / "action-validation.yaml"), alert_pass_count=3)
        self.assertEqual(r["state"], "NOT_READY")
        self.assertEqual(r["reasons"], ["delivery is not validated: problem_delivery not verified with evidence; recovery_delivery not verified with evidence; "
                                        "interface_exclusion not verified with evidence; validated_by missing"])


class TestRawInputCounts(unittest.TestCase):
    def host(self):
        fz = FakeZabbix()
        hid = fz.add_host("IOSV-1", templates=["Cisco IOS by SNMP"])
        for k in ("sensor.fans.walk", "sensor.psu.walk", "sensor.temp.walk"):
            fz.add_item(hid, k, snmp_oid="walk[1.3.6.1.4.1.9.9.13]", lastclock=0, value_type="4")
        for k in ("net.if.walk", "system.cpu.walk"):                       # other raw inputs, not environmental
            fz.add_item(hid, k, snmp_oid="walk[1.3.6.1.2.1.2]", lastclock=0, value_type="4")
        return fz

    def test_total_is_kept_and_the_environmental_subset_is_reported(self):
        d = AU.discover_host(ZabbixAPI("https://f.example", "t", transport=self.host()), "IOSV-1", NOW)
        self.assertEqual(d["raw_input_count"], 5)
        self.assertEqual(d["environmental_raw_input_count"], 3)
        self.assertEqual(sorted(r["key"] for r in d["raw_inputs"] if r["environmental"]), ["sensor.fans.walk", "sensor.psu.walk", "sensor.temp.walk"])
        self.assertEqual(d["candidate_sensor_count"], 0)

    def test_verify_host_reports_both_counts(self):
        h = audit_host(self.host(), cisco_policy([], expected=("fan",)), name="IOSV-1")
        self.assertEqual((h["raw_input_count"], h["environmental_raw_input_count"]), (5, 3))


class TestMissingUnreachableStale(unittest.TestCase):
    """The three look different and are reported differently."""

    def test_missing_item_is_a_configuration_gap_even_when_the_device_is_down(self):
        fz, hid, iid = good_fake()
        fz.hosts[hid]["interfaces"][0]["available"] = "2"
        h = audit_host(fz, cisco_policy([fan_sensor("sensor.fan.status[9]")]))
        s = h["categories"]["fan"]["sensors"][0]
        self.assertEqual((s["verdict"], s["reason"]), (AU.GAP, "ITEM_MISSING"))
        self.assertIn("whether or not the device is reachable", s["detail"])

    def test_existing_item_on_an_unreachable_device_is_blocked(self):
        fz, hid, iid = good_fake(lastclock=NOW - 99999, state="1", error="Timeout")
        fz.hosts[hid]["interfaces"][0]["available"] = "2"
        s = audit_host(fz, cisco_policy([fan_sensor()]))["categories"]["fan"]["sensors"][0]
        self.assertEqual((s["verdict"], s["reason"], s["reachability"]), (AU.BLOCKED, "HOST_UNREACHABLE", "unreachable"))

    def test_stale_on_a_reachable_device_is_a_polling_gap_not_a_hardware_fault(self):
        fz, hid, iid = good_fake(lastclock=NOW - 99999)
        s = audit_host(fz, cisco_policy([fan_sensor()]))["categories"]["fan"]["sensors"][0]
        self.assertEqual((s["verdict"], s["reason"], s["reachability"]), (AU.GAP, "STALE", "available"))
        self.assertIn("not a hardware fault", s["detail"])
        self.assertIsNone(s["current_state"])

    def test_unknown_reachability_is_not_treated_as_unreachable(self):
        fz, hid, iid = good_fake(lastclock=NOW - 99999)
        fz.hosts[hid]["interfaces"][0]["available"] = "0"
        s = audit_host(fz, cisco_policy([fan_sensor()]))["categories"]["fan"]["sensors"][0]
        self.assertEqual((s["reason"], s["reachability"]), ("STALE", "unknown"))

    def test_host_without_a_polling_interface_has_no_inferred_reachability(self):
        fz, hid, iid = good_fake()
        fz.hosts[hid]["interfaces"] = []
        h = audit_host(fz, cisco_policy([fan_sensor()]))
        self.assertEqual(h["monitoring_quality"]["state"], "none")
        self.assertEqual(h["verdict"], AU.PASS)


class ActionProject(unittest.TestCase):
    def setUp(self):
        self.fz = FakeZabbix()
        self.fz.usergroups.append({"usrgrpid": "9", "name": "Zabbix administrators"})
        self.p = Project(fake=self.fz)

    def tearDown(self):
        self.p.close()

    def cfg(self, text):
        self.p.write("config/notifications.lab.yaml", text)


class TestExplicitRecipients(ActionProject):
    def test_shipped_example_is_refused_until_an_operator_fills_it_in(self):
        with self.assertRaises(AuditError):
            A.load_spec(str(ROOT / "config" / "notifications.example.yaml"))

    def test_approval_fields_are_mandatory(self):
        for text in ("media_type: Telegram\nusergroups: [Network Operations]\n",
                     "media_type: Telegram\nusergroups: [Network Operations]\napproved_by: ''\napproval_reference: T-1\n",
                     "media_type: Telegram\nusergroups: [Network Operations]\napproved_by: noc-lead\n"):
            self.cfg(text)
            rc, out, err = self.p.run("--env", "lab", "action", "plan")
            self.assertEqual(rc, 3)
            self.assertIn("explicitly approved", err)

    def test_empty_group_list_is_refused(self):
        self.cfg("media_type: Telegram\nusergroups: []\napproved_by: noc-lead\napproval_reference: T-1\n")
        self.assertEqual(self.p.run("--env", "lab", "action", "plan")[0], 3)

    def test_an_absent_group_is_never_replaced_by_administrators(self):
        self.cfg("media_type: Telegram\nusergroups: [Network Operations]\napproved_by: noc-lead\napproval_reference: T-1\n")
        self.fz.usergroups[:] = [{"usrgrpid": "9", "name": "Zabbix administrators"}]          # the only group that exists
        rc, out, err = self.p.run("--env", "lab", "action", "plan")
        self.assertEqual(rc, 1)
        self.assertIn("user group 'Network Operations' not found", out)
        rc, out, err = self.p.run("--env", "lab", "action", "apply")
        self.assertEqual(rc, 3)
        self.assertEqual(self.fz.writes(), [])
        self.assertEqual([a for a in self.fz.actions.values() if a["name"] == A.ACTION_NAME], [])

    def test_the_applied_action_carries_exactly_the_approved_group(self):
        self.cfg("media_type: Telegram\nusergroups: [Network Operations]\napproved_by: noc-lead\napproval_reference: CHG-77\n")
        rc, out, err = self.p.run("--env", "lab", "action", "apply")
        self.assertEqual(rc, 0, err + out)
        a = [x for x in self.fz.actions.values() if x["name"] == A.ACTION_NAME][0]
        groups = [g["usrgrpid"] for o in a["operations"] + a["recovery_operations"] for g in o["opmessage_grp"]]
        self.assertEqual(set(groups), {"7"})                     # Network Operations only, never 9 (Zabbix administrators)
        self.assertEqual(a["status"], "1")

    def test_preserved_exclusion_and_disabled_default(self):
        self.assertEqual([r for r in A.crossover_report() if not r["ok"]], [])
        self.assertEqual(A.build_params("3", ["7"], enabled=False)["status"], 1)
        self.assertEqual(A.hardware_filter()["evaltype"], 1)


if __name__ == "__main__":
    unittest.main()


class TestClassifierTemp(unittest.TestCase):
    def test_temp_walk_is_environmental(self):
        from hwh import items as I
        self.assertEqual(I.classify("sensor.temp.walk"), ["temperature"])
        self.assertEqual(I.classify("sensor.fans.walk"), ["fan"])
        self.assertEqual(I.classify("sensor.psu.walk"), ["power"])
        self.assertEqual(I.classify("template version"), [])        # 'temp' only as a whole word, never inside 'template'

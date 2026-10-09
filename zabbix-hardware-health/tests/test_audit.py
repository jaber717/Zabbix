"""Regression tests for every defect found in the 2026-10-09 LAB discovery, plus the rules that stop keyword-only coverage."""
import unittest

from hwh import audit as AU
from hwh import items as I
from hwh import semantics
from hwh.api import ZabbixAPI
from tests.fakes import NOW, FakeZabbix
from tests.helpers import SYNTHETIC, TAGS_FAN, audit_host, cisco_policy, fan_sensor, good_fake


def reason(h, cat="fan", idx=0):
    return h["categories"][cat]["sensors"][idx]["reason"]


class TestRawInputsAreNotSensors(unittest.TestCase):
    """Defect 1: IOSv sensor.fans/psu/temp.walk raw inputs were counted as one sensor each."""

    def raw_only_host(self):
        fz = FakeZabbix()
        hid = fz.add_host("IOSV-1", templates=["Cisco IOS by SNMP"])
        for k in ("sensor.fans.walk", "sensor.psu.walk", "sensor.temp.walk"):
            fz.add_item(hid, k, snmp_oid="walk[1.3.6.1.4.1.9.9.13]", lastclock=0, value_type="4")
        return fz

    def test_discover_counts_zero_sensors_and_three_raw_inputs(self):
        api = ZabbixAPI("https://f.example", "t", transport=self.raw_only_host())
        d = AU.discover_host(api, "IOSV-1", NOW)
        self.assertEqual(d["raw_input_count"], 3)
        self.assertEqual(d["candidate_sensor_count"], 0)
        self.assertEqual(d["candidates"], [])

    def test_declaring_a_raw_walk_as_a_sensor_is_a_gap_not_coverage(self):
        fz = self.raw_only_host()
        h = audit_host(fz, cisco_policy([{"category": "temperature", "key": "sensor.temp.walk", "units": "C"}], expected=("temperature",)), name="IOSV-1")
        self.assertEqual(h["verdict"], AU.GAP)
        self.assertEqual(reason(h, "temperature"), "ITEM_IS_RAW_INPUT")
        self.assertEqual(h["concrete_sensor_count"], 0)

    def test_walk_by_oid_by_key_and_by_master_role_are_all_raw(self):
        masters = {"7"}
        self.assertIsNotNone(I.raw_reason({"itemid": "1", "key_": "x", "snmp_oid": "walk[1.2]"}, masters))
        self.assertIsNotNone(I.raw_reason({"itemid": "1", "key_": "sensor.fans.walk", "snmp_oid": ""}, masters))
        self.assertIsNotNone(I.raw_reason({"itemid": "1", "key_": "walk[1.2.3]", "snmp_oid": ""}, masters))
        self.assertIsNotNone(I.raw_reason({"itemid": "7", "key_": "anything", "snmp_oid": ""}, masters))
        self.assertIsNone(I.raw_reason({"itemid": "1", "key_": "sensor.fan.status[1]", "snmp_oid": "get[1.2.3]"}, masters))
        self.assertIsNone(I.raw_reason({"itemid": "1", "key_": "walkthrough.status", "snmp_oid": ""}, masters))

    def test_a_dependent_sensor_is_concrete_even_though_its_master_is_raw(self):
        fz, hid, iid = good_fake()
        api = ZabbixAPI("https://f.example", "t", transport=fz)
        d = AU.discover_host(api, "NX-01", NOW)
        self.assertEqual(d["raw_input_count"], 1)
        self.assertEqual([c["key"] for c in d["candidates"]], ["sensor.fan.status[1]"])


class TestEvidenceIsCaptured(unittest.TestCase):
    """Defect 2: lastvalue, units, OID, preprocessing, value map and model identity were never read."""

    def test_discover_returns_the_fields_needed_for_the_matrix(self):
        fz, hid, iid = good_fake()
        fz.add_item(hid, "system.hw.model", name="Hardware model name", lastvalue="N9K-C9336C-TEST", value_type="1")
        fz.add_item(hid, "sensor.temp.inlet", name="Inlet temperature", lastvalue="31", units="°C", snmp_oid="get[1.2.3.4]", lastclock=NOW - 30)
        d = AU.discover_host(ZabbixAPI("https://f.example", "t", transport=fz), "NX-01", NOW)
        fan = next(c for c in d["candidates"] if c["key"] == "sensor.fan.status[1]")
        self.assertEqual(fan["lastvalue"], "10")
        self.assertEqual(fan["age_seconds"], 60)
        self.assertTrue(fan["lastclock_utc"].startswith("1970-01-12"))
        self.assertEqual(fan["snmp_oid"], "get[1.2.3.1]")
        self.assertEqual(fan["preprocessing"], [{"type": "1", "params": "1"}])
        self.assertEqual(fan["valuemap"]["mappings"], [{"value": "10", "newvalue": "ok"}])
        self.assertTrue(fan["supported"] and fan["enabled"])
        temp = next(c for c in d["candidates"] if c["key"] == "sensor.temp.inlet")
        self.assertEqual(temp["units"], "°C")
        self.assertEqual(d["identity"]["inventory"]["model"], "N9K-TEST")
        self.assertEqual(d["identity"]["items"][0]["value"], "N9K-C9336C-TEST")

    def test_discover_never_declares_coverage(self):
        fz, hid, iid = good_fake()
        d = AU.discover_host(ZabbixAPI("https://f.example", "t", transport=fz), "NX-01", NOW)
        self.assertTrue(all(c["verdict"] == "CANDIDATE_UNVERIFIED" for c in d["candidates"]))
        self.assertIn("NOT coverage", d["note"])
        self.assertNotIn("verdict", d)

    def test_discover_unknown_host(self):
        d = AU.discover_host(ZabbixAPI("https://f.example", "t", transport=FakeZabbix()), "NOPE", NOW)
        self.assertFalse(d["found"])


class TestNoKeywordOnlyCoverage(unittest.TestCase):
    """Defect 3: items and triggers were matched to a category by NAME TEXT only."""

    def settings(self):
        return cisco_policy([fan_sensor()])

    def test_fully_evidenced_sensor_passes(self):
        fz, hid, iid = good_fake()
        h = audit_host(fz, self.settings())
        self.assertEqual(h["verdict"], AU.PASS, h)
        s = h["categories"]["fan"]["sensors"][0]
        self.assertEqual(s["current_state"], "normal")
        self.assertEqual(h["concrete_sensor_count"], 1)
        self.assertEqual(h["raw_input_count"], 1)

    def test_undeclared_keyword_sensor_is_never_coverage(self):
        fz, hid, iid = good_fake()
        h = audit_host(fz, cisco_policy([], expected=("fan",)))
        self.assertEqual(h["categories"]["fan"]["verdict"], AU.GAP)
        self.assertEqual(h["categories"]["fan"]["reason"], "NO_DECLARED_SENSOR")

    def test_trigger_that_only_mentions_the_component_in_its_name_does_not_count(self):
        fz, hid, iid = good_fake()
        fz.triggers[hid] = []
        other = fz.add_item(hid, "icmpping", name="Ping")
        fz.add_trigger(hid, "Fan 1 failed", [other], tags=TAGS_FAN)          # name says fan; bound to an unrelated item
        h = audit_host(fz, self.settings())
        self.assertEqual(reason(h), "NO_TRIGGER")

    def test_disabled_trigger_does_not_count(self):
        fz, hid, iid = good_fake()
        fz.triggers[hid][0]["status"] = "1"
        self.assertEqual(reason(audit_host(fz, self.settings())), "NO_TRIGGER")

    def test_trigger_without_dedicated_tags_is_not_routable(self):
        for tags in ((), (("scope", "availability"),), (("netops_hardware", "1"),), (("netops_hardware", "1"), ("hardware_component", "power"))):
            fz, hid, iid = good_fake()
            fz.triggers[hid][0]["tags"] = [{"tag": k, "value": v} for k, v in tags]
            self.assertEqual(reason(audit_host(fz, self.settings())), "TRIGGER_NOT_ROUTABLE", tags)

    def test_trigger_tagged_for_both_actions_is_a_gap(self):
        fz, hid, iid = good_fake()
        fz.triggers[hid][0]["tags"].append({"tag": "netops_alert", "value": "link_down"})
        self.assertEqual(reason(audit_host(fz, self.settings())), "TRIGGER_CROSS_TAGGED")

    def test_missing_item(self):
        fz, hid, iid = good_fake()
        h = audit_host(fz, cisco_policy([fan_sensor("sensor.fan.status[9]")]))
        self.assertEqual(reason(h), "ITEM_MISSING")


class TestStatusSemanticsAreNeverInvented(unittest.TestCase):
    """Task 5: a vendor status code is interpreted only through a VERIFIED, vendor-matched mapping."""

    def test_shipped_registry_is_empty(self):
        import pathlib
        reg = semantics.load(str(pathlib.Path(__file__).resolve().parents[1] / "config" / "status-semantics.yaml"))
        self.assertEqual(reg, {})

    def test_empty_registry_means_semantics_unverified(self):
        fz, hid, iid = good_fake()
        h = audit_host(fz, cisco_policy([fan_sensor()]), reg={})
        self.assertEqual(reason(h), "SEMANTICS_UNVERIFIED")
        self.assertIsNone(h["categories"]["fan"]["sensors"][0]["current_state"])

    def test_unverified_entry_is_unusable(self):
        fz, hid, iid = good_fake()
        s = dict(fan_sensor(), semantics="test-status-unverified")
        self.assertEqual(reason(audit_host(fz, cisco_policy([s]))), "SEMANTICS_UNVERIFIED")

    def test_mapping_verified_for_another_vendor_is_refused(self):
        fz, hid, iid = good_fake()
        s = dict(fan_sensor(), semantics="test-status-huawei")
        h = audit_host(fz, cisco_policy([s]))
        self.assertEqual(reason(h), "SEMANTICS_UNVERIFIED")
        self.assertIn("vendor", h["categories"]["fan"]["sensors"][0]["detail"])

    def test_evidence_is_mandatory(self):
        reg = semantics.validate({"semantics": {"x": {"vendor": "cisco", "evidence": "", "verified": True, "states": {"1": "normal"}}}})
        self.assertIsNotNone(semantics.usable(reg, "x", "cisco", "cisco-nxos")[1])

    def test_unmapped_value_is_a_gap_not_healthy_or_failed(self):
        fz, hid, iid = good_fake(lastvalue="99")
        self.assertEqual(reason(audit_host(fz, cisco_policy([fan_sensor()]))), "VALUE_UNMAPPED")

    def test_failed_and_degraded_values_are_reported_but_coverage_is_still_pass(self):
        for raw, state in (("30", "failed"), ("20", "degraded"), ("40", "absent")):
            fz, hid, iid = good_fake(lastvalue=raw)
            h = audit_host(fz, cisco_policy([fan_sensor()]))
            self.assertEqual(h["verdict"], AU.PASS)
            self.assertEqual(h["categories"]["fan"]["sensors"][0]["current_state"], state)

    def test_registry_validation_rejects_bad_state_names_and_missing_normal(self):
        from hwh.api import AuditError
        with self.assertRaises(AuditError):
            semantics.validate({"semantics": {"x": {"vendor": "cisco", "evidence": "e" * 12, "verified": True, "states": {"1": "healthy"}}}})
        with self.assertRaises(AuditError):
            semantics.validate({"semantics": {"x": {"vendor": "cisco", "evidence": "e" * 12, "verified": True, "states": {"1": "failed"}}}})


class TestFreshnessAndReachability(unittest.TestCase):
    def test_never_collected(self):
        fz, hid, iid = good_fake(lastclock=0)
        self.assertEqual(reason(audit_host(fz, cisco_policy([fan_sensor()]))), "NEVER_COLLECTED")

    def test_stale(self):
        fz, hid, iid = good_fake(lastclock=NOW - 3600)
        self.assertEqual(reason(audit_host(fz, cisco_policy([fan_sensor()]))), "STALE")

    def test_unsupported_and_disabled(self):
        fz, hid, iid = good_fake(state="1", error="no such object")
        self.assertEqual(reason(audit_host(fz, cisco_policy([fan_sensor()]))), "ITEM_UNSUPPORTED")
        fz, hid, iid = good_fake(status="1")
        self.assertEqual(reason(audit_host(fz, cisco_policy([fan_sensor()]))), "ITEM_DISABLED")

    def test_unreachable_device_is_blocked_not_a_failed_sensor(self):
        fz, hid, iid = good_fake(lastclock=NOW - 36000, state="1", error="Timeout while connecting")
        fz.hosts[hid]["interfaces"][0]["available"] = "2"
        h = audit_host(fz, cisco_policy([fan_sensor()]))
        self.assertEqual(h["verdict"], AU.BLOCKED)
        self.assertEqual(reason(h), "HOST_UNREACHABLE")
        self.assertIsNone(h["categories"]["fan"]["sensors"][0]["current_state"])

    def test_one_available_interface_is_not_unreachable(self):
        fz, hid, iid = good_fake()
        fz.hosts[hid]["interfaces"] = [{"interfaceid": "1", "type": "2", "main": "1", "available": "2", "error": ""},
                                       {"interfaceid": "2", "type": "2", "main": "0", "available": "1", "error": ""}]
        self.assertEqual(audit_host(fz, cisco_policy([fan_sensor()]))["verdict"], AU.PASS)

    def test_host_missing_and_disabled_are_blocked(self):
        fz = FakeZabbix()
        self.assertEqual(audit_host(fz, cisco_policy([fan_sensor()]), name="GHOST")["verdict"], AU.BLOCKED)
        fz, hid, iid = good_fake()
        fz.hosts[hid]["status"] = "1"
        h = audit_host(fz, cisco_policy([fan_sensor()]))
        self.assertEqual(h["verdict"], AU.BLOCKED)
        self.assertEqual(h["host_status"], "HOST_DISABLED")


class TestTemperature(unittest.TestCase):
    def host(self, value="31", units="°C"):
        fz = FakeZabbix()
        hid = fz.add_host("NX-01")
        iid = fz.add_item(hid, "sensor.temp.inlet", lastvalue=value, units=units, value_type="0")
        fz.add_trigger(hid, "Inlet too hot", [iid], tags=(("netops_hardware", "1"), ("hardware_component", "temperature")))
        return fz

    def pol(self, **kw):
        s = {"category": "temperature", "key": "sensor.temp.inlet", "units": "C", "plausible_range": [0, 120]}
        s.update(kw)
        return cisco_policy([s], expected=("temperature",))

    def test_celsius_spellings_match_and_value_is_reported(self):
        for u in ("°C", "C", "degC", "Celsius"):
            h = audit_host(self.host(units=u), self.pol())
            self.assertEqual(h["verdict"], AU.PASS, u)
        self.assertIn("31", h["categories"]["temperature"]["sensors"][0]["current_state"])

    def test_wrong_units_nonnumeric_and_implausible_are_gaps(self):
        self.assertEqual(reason(audit_host(self.host(units="F"), self.pol()), "temperature"), "UNITS_MISMATCH")
        self.assertEqual(reason(audit_host(self.host(units=""), self.pol()), "temperature"), "UNITS_MISMATCH")
        self.assertEqual(reason(audit_host(self.host(value="ok"), self.pol()), "temperature"), "VALUE_NOT_NUMERIC")
        self.assertEqual(reason(audit_host(self.host(value="3100"), self.pol()), "temperature"), "VALUE_IMPLAUSIBLE")


class TestHaIsSeparateFromHardwareRedundancy(unittest.TestCase):
    """Defect 4: FortiGate ha.* items were not recognised; HA must never stand in for fan/PSU redundancy (or the reverse)."""

    def test_classification_keeps_them_apart(self):
        self.assertEqual(I.classify("ha.sync.status"), ["ha"])
        self.assertEqual(I.classify("FortiGate HA member sync"), ["ha"])
        self.assertEqual(I.classify("HA cluster state"), ["ha"])
        self.assertEqual(I.classify("Power supply redundancy lost"), ["hw_redundancy"])
        self.assertEqual(I.classify("HA redundancy state"), ["ha"])
        self.assertEqual(I.classify("PowerSupply-2 Fan operational status"), ["fan"])
        self.assertEqual(I.classify("Interface Gi0/1 speed"), [])

    def forti(self):
        fz = FakeZabbix()
        hid = fz.add_host("DR-FW01", templates=["FortiGate by SNMP"])
        for k in ("ha.mode", "ha.group.name", "ha.sync.status", "ha.member.state"):
            fz.add_item(hid, k, lastclock=0, lastvalue="")
        return fz, hid

    def policy(self, sensors, expected):
        return {"site": "DR", "vendor": "fortinet", "family": "fortinet-fortigate", "model": "TEST-FG", "expected": expected, "sensors": sensors,
                "max_sensor_age_minutes": 10}

    def test_static_undated_ha_items_without_trigger_are_not_covered(self):
        fz, hid = self.forti()
        reg = semantics.validate({"semantics": {"fg-ha": {"vendor": "fortinet", "evidence": "synthetic test fixture", "verified": True, "states": {"1": "normal"}}}})
        h = audit_host(fz, self.policy([{"category": "ha", "key": "ha.member.state", "semantics": "fg-ha"}], ["ha"]), reg=reg, name="DR-FW01")
        self.assertEqual(h["verdict"], AU.GAP)
        self.assertEqual(reason(h, "ha"), "NEVER_COLLECTED")

    def test_ha_sensors_cannot_satisfy_hardware_redundancy_and_vice_versa(self):
        fz, hid = self.forti()
        reg = semantics.validate({"semantics": {"fg-ha": {"vendor": "fortinet", "evidence": "synthetic test fixture", "verified": True, "states": {"1": "normal"}}}})
        h = audit_host(fz, self.policy([{"category": "ha", "key": "ha.member.state", "semantics": "fg-ha"}], ["ha", "hw_redundancy"]), reg=reg, name="DR-FW01")
        self.assertEqual(h["categories"]["hw_redundancy"]["reason"], "NO_DECLARED_SENSOR")

    def test_trigger_component_tag_must_match_the_category(self):
        fz, hid = self.forti()
        iid = fz.add_item(hid, "ha.peer.state", lastvalue="1")
        fz.add_trigger(hid, "HA peer lost", [iid], tags=(("netops_hardware", "1"), ("hardware_component", "redundancy")))
        reg = semantics.validate({"semantics": {"fg-ha": {"vendor": "fortinet", "evidence": "synthetic test fixture", "verified": True, "states": {"1": "normal"}}}})
        h = audit_host(fz, self.policy([{"category": "ha", "key": "ha.peer.state", "semantics": "fg-ha"}], ["ha"]), reg=reg, name="DR-FW01")
        self.assertEqual(reason(h, "ha"), "TRIGGER_NOT_ROUTABLE")                    # tagged 'redundancy', category is 'ha'


class TestReadOnlyAllowlist(unittest.TestCase):
    def test_audit_makes_only_read_calls(self):
        fz, hid, iid = good_fake()
        audit_host(fz, cisco_policy([fan_sensor()]))
        self.assertEqual(fz.writes(), [])
        self.assertTrue(set(fz.methods()) <= {"host.get", "item.get", "trigger.get"})

    def test_writes_are_refused_by_the_client(self):
        from hwh.api import AuditError
        api = ZabbixAPI("https://f.example", "t", transport=FakeZabbix())
        for m in ("trigger.update", "item.create", "host.update", "action.create", "usermacro.create", "configuration.import"):
            with self.assertRaises(AuditError):
                api.call(m, {})

    def test_action_writes_need_an_explicit_write_client(self):
        from hwh.api import AuditError
        with self.assertRaises(AuditError):
            ZabbixAPI("https://f.example", "t", transport=FakeZabbix()).call("action.delete", ["1"])
        fz = FakeZabbix()
        ZabbixAPI("https://f.example", "t", transport=fz, write=True).call("action.delete", ["1"])
        self.assertEqual(fz.writes(), ["action.delete"])

    def test_the_token_is_never_in_an_error(self):
        from hwh.api import AuditError
        fz = FakeZabbix()
        api = ZabbixAPI("https://f.example", "SECRET-TOKEN-123", transport=fz)
        try:
            api.call("host.get", {"nonexistent": 1})
            api.call("item.get", {})
        except (AuditError, KeyError) as exc:
            self.assertNotIn("SECRET-TOKEN-123", str(exc))


if __name__ == "__main__":
    unittest.main()

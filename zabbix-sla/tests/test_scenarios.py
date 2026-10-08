"""Behavioural tests of the service model: what is (not) 'down' for a given set of Zabbix problems.

These prove the MODEL (compiled tree + documented Zabbix status algorithms). Whether the live server evaluates identically is the
live acceptance matrix (A-01 .. A-08); a model of Zabbix is not Zabbix.
"""
import datetime
import os
import unittest

from slaas import evaluator as E
from slaas import inventory, model, tags as T

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))


def compiled(path, assume="and"):
    data = inventory.load_file(path)
    data["tag_semantics"] = assume
    inv = inventory.validate(data)
    assert not inv.errors, [str(p) for p in inv.errors]
    return model.compile_inventory(inv)


class LabScenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = compiled(os.path.join(ROOT, "inventory", "lab.yaml"))

    def down(self, *problems):
        return E.down_services(self.d, list(problems))

    def test_healthy_network_has_nothing_down(self):
        self.assertEqual(self.down(), [])

    def test_single_isp_failure_does_not_mark_internet_down(self):
        for lid in ("int-core--mobily", "int-core--stc", "mobily--site-a", "stc--site-b"):
            down = self.down(E.netops_link_down(lid))
            self.assertNotIn("svc.siteA.internet", down, lid)
            self.assertNotIn("svc.siteB.internet", down, lid)
            self.assertNotIn("conn.siteA.international", down, lid)
            self.assertNotIn("root", down, lid)

    def test_single_isp_failure_is_still_visible_at_path_and_component_level(self):
        down = self.down(E.netops_link_down("int-core--mobily"))
        self.assertIn("lnk.int-core--mobily", down)
        self.assertIn("path.siteA.intl.direct", down)
        self.assertNotIn("path.siteA.intl.via-siteB", down)

    def test_both_isps_down_marks_both_sites_internet_down(self):
        down = self.down(E.netops_link_down("int-core--mobily"), E.netops_link_down("int-core--stc"))
        for s in ("svc.siteA.internet", "svc.siteB.internet", "conn.siteA.international", "conn.siteB.international", "root"):
            self.assertIn(s, down)
        self.assertNotIn("svc.siteA.national", down)                 # SAIX is a separate service

    def test_inter_edge_failure_degrades_redundancy_but_not_direct_internet(self):
        down = self.down(E.netops_link_down("site-a--site-b"))
        self.assertNotIn("svc.siteA.internet", down)
        self.assertNotIn("svc.siteB.internet", down)
        self.assertIn("path.siteA.intl.via-siteB", down)

    def test_inter_edge_plus_site_a_isp_failure_cuts_site_a(self):
        down = self.down(E.netops_link_down("site-a--site-b"), E.netops_link_down("mobily--site-a"))
        self.assertIn("svc.siteA.internet", down)
        self.assertNotIn("svc.siteB.internet", down)

    def test_inter_site_is_down_when_the_only_modelled_path_is_down(self):
        # the transit fallback is NOT assumed (unverified), so this service has no modelled redundancy
        down = self.down(E.netops_link_down("site-a--site-b"))
        self.assertIn("svc.inter-site", down)

    def test_national_has_no_assumed_transit_fallback(self):
        down = self.down(E.netops_link_down("saix-a--site-a"), E.netops_link_down("saix-b--site-b"))
        self.assertIn("svc.siteA.national", down)
        self.assertIn("svc.siteB.national", down)
        self.assertNotIn("svc.siteA.internet", down)

    def test_national_survives_one_saix_leg_through_the_inter_edge(self):
        down = self.down(E.netops_link_down("saix-a--site-a"))
        self.assertNotIn("svc.siteA.national", down)

    def test_utilization_and_other_nonavailability_alerts_are_not_downtime(self):
        for alert in T.NETOPS_NON_AVAILABILITY:
            for lid in ("int-core--mobily", "int-core--stc", "stc--site-b", "mobily--site-a", "site-a--site-b", "saix-a--site-a"):
                self.assertEqual(self.down(E.netops_alert(lid, alert, severity=5)), [], "%s on %s must not count as downtime" % (alert, lid))

    def test_every_link_condition_pins_both_identity_and_availability(self):
        for sid, s in self.d.services.items():
            if s["layer"] == "component":
                names = sorted(t for t, _, _ in s["problem_tags"])
                self.assertEqual(names, ["link_id", "netops_alert"], sid)

    def test_no_service_condition_uses_a_volatile_or_unstable_tag(self):
        for sid, s in self.d.services.items():
            for tag, _, _ in s["problem_tags"]:
                self.assertTrue(T.condition_ok(tag), "%s uses forbidden tag %s" % (sid, tag))

    def test_every_managed_service_is_tagged_and_unique(self):
        names = [s["name"] for s in self.d.services.values()]
        self.assertEqual(len(names), len(set(names)))
        for sid, s in self.d.services.items():
            self.assertEqual(s["tags"][T.MANAGED_KEY], T.MANAGED_VALUE)
            self.assertEqual(s["tags"][T.ID_KEY], sid)

    def test_parallel_services_always_have_two_or_more_children(self):
        for sid, s in self.d.services.items():
            if s["algorithm"] == model.ALGO_PARALLEL:
                self.assertGreaterEqual(len(s["children"]), 2, sid)

    def test_declared_but_unmodelled_redundancy_is_reported(self):
        self.assertTrue(any("NO redundancy is represented" in n for n in self.d.notes))

    def test_partial_coverage_links_are_reported(self):
        self.assertTrue(any("signal_coverage partial" in n and "saix-core--saix-a" in n for n in self.d.notes))

    def test_verified_services_are_deferred_until_probes_are_active(self):
        self.assertNotIn("svc.siteA.internet.verified", self.d.services)
        self.assertTrue(any("svc.siteA.internet.verified" in x for x in self.d.deferred))

    def test_semantics_unknown_compiles_nothing_for_links(self):
        inv = inventory.load(os.path.join(ROOT, "inventory", "lab.yaml"))
        self.assertTrue(any("tag_semantics" in p.where for p in inv.errors))
        d = model.compile_inventory(inv)
        self.assertFalse([s for s in d.services.values() if s["layer"] == "component"])


class Hazard(unittest.TestCase):
    def test_if_or_semantics_were_live_utilization_would_become_downtime(self):
        """Documents WHY gate E-01 exists: under OR, a utilisation alert on lx matches the link_id condition."""
        d = compiled(os.path.join(ROOT, "inventory", "lab.yaml"))
        problems = [E.netops_alert("int-core--mobily", "util_rx"), E.netops_alert("int-core--stc", "util_rx")]
        self.assertEqual(E.down_services(d, problems, "and"), [])
        self.assertIn("svc.siteA.internet", E.down_services(d, problems, "or"))


class MiniVerified(unittest.TestCase):
    def setUp(self):
        from tests.helpers import MINI
        data = inventory.yaml.load(MINI, Loader=inventory.UniqueKeyLoader)
        self.d = model.compile_inventory(inventory.validate(data))

    def test_probe_failure_breaks_verified_but_not_inferred(self):
        down = E.down_services(self.d, [E.probe_down("probe.net")])
        self.assertIn("svc.net.verified", down)
        self.assertNotIn("svc.net", down)

    def test_stale_probe_is_a_quality_signal_not_downtime(self):
        down = E.down_services(self.d, [E.probe_stale("probe.net")])
        self.assertNotIn("svc.net.verified", down)
        self.assertNotIn("svc.net", down)
        self.assertIn("quality.probe.net", down)
        self.assertIn("quality.root", down)
        self.assertNotIn("root", down)

    def test_probe_up_and_links_down_marks_inferred_but_not_verified(self):
        down = E.down_services(self.d, [E.netops_link_down("ly"), E.netops_link_down("lz")])
        self.assertIn("svc.net", down)
        self.assertIn("svc.net.verified", down)            # series: it also requires conn.net

    def test_redundant_pair_needs_both_paths_down(self):
        self.assertNotIn("svc.net", E.down_services(self.d, [E.netops_link_down("lx")]))
        self.assertNotIn("svc.net", E.down_services(self.d, [E.netops_link_down("lz")]))
        self.assertIn("svc.net", E.down_services(self.d, [E.netops_link_down("lx"), E.netops_link_down("lz")]))


class InventoryValidation(unittest.TestCase):
    def v(self, text, now=None):
        from tests.helpers import MINI
        data = inventory.yaml.load(text, Loader=inventory.UniqueKeyLoader)
        return inventory.validate(data, now)

    def errs(self, text, now=None):
        return [str(p) for p in self.v(text, now).errors]

    def mini(self, old, new):
        from tests.helpers import MINI
        self.assertIn(old, MINI)
        return MINI.replace(old, new)

    def test_mini_is_valid(self):
        from tests.helpers import MINI
        self.assertEqual(self.errs(MINI), [])

    def test_probe_needs_two_destinations(self):
        t = self.mini("      - {name: d2, address: 192.0.2.2, check: icmp}\n      - {name: d3, address: 192.0.2.3, check: icmp}\n", "").replace("quorum: 2", "quorum: 1")
        self.assertTrue(any("at least 2 destinations" in e for e in self.errs(t)))

    def test_quorum_is_explicit_and_bounded(self):
        self.assertTrue(any("quorum" in e for e in self.errs(self.mini("quorum: 2", "quorum: 4"))))
        self.assertTrue(any("quorum" in e for e in self.errs(self.mini("    quorum: 2\n", ""))))

    def test_probe_without_routing_proof_cannot_back_verified_when_active(self):
        self.assertTrue(any("no routing proof" in e for e in self.errs(self.mini("verification: pinned_destination", "verification: none"))))

    def test_unknown_semantics_is_a_hard_gate(self):
        self.assertTrue(any("tag_semantics" in e for e in self.errs(self.mini("tag_semantics: and", "tag_semantics: unknown"))))

    def test_slo_range(self):
        self.assertTrue(any("slo" in e for e in self.errs(self.mini("slo: 99.9", "slo: 100.5"))))

    def test_approved_must_be_explicit(self):
        self.assertTrue(any("approved" in e for e in self.errs(self.mini("slo: 99.9, approved: true", "slo: 99.9"))))

    def test_effective_date_must_be_fixed(self):
        self.assertTrue(any("effective_date" in e for e in self.errs(self.mini("effective_date: 2026-01-01, timezone: Asia/Riyadh}\n  ver", "effective_date: today, timezone: Asia/Riyadh}\n  ver"))))

    def test_unknown_reference_and_unknown_key(self):
        self.assertTrue(any("unknown component" in e for e in self.errs(self.mini("components: [c.z]", "components: [c.nope]"))))
        self.assertTrue(any("unknown" in e for e in self.errs(self.mini("c.z: {kind: link, link_id: lz}", "c.z: {kind: link, link_id: lz, colour: red}"))))

    def test_duplicate_link_id_and_duplicate_ids(self):
        self.assertTrue(any("already used" in e for e in self.errs(self.mini("link_id: lz", "link_id: lx"))))

    def test_duplicate_yaml_key_is_rejected(self):
        from slaas._compat import ConfigError
        with self.assertRaises(Exception):
            inventory.yaml.load("a: 1\na: 2\n", Loader=inventory.UniqueKeyLoader)

    def test_unverified_fallback_is_excluded_not_assumed(self):
        t = self.mini("members: [p.a, p.b]", "members: [p.a, {ref: p.b, fallback_via_transit: true, verified: false}]")
        inv = self.v(t)
        self.assertEqual([str(p) for p in inv.errors], [])
        d = model.compile_inventory(inv)
        self.assertEqual(d.services["conn.net"]["children"], ["p.a"])
        self.assertEqual(d.services["conn.net"]["algorithm"], model.ALGO_SERIES)

    def test_reference_cycle(self):
        t = self.mini("members: [p.a, p.b]", "members: [p.a, conn.net]")
        self.assertTrue(any("cycle" in e for e in self.errs(t)))

    def test_planned_downtime_policy(self):
        pd = ("planned_downtime:\n  - {id: pd1, slas: [std], start: '2026-10-10T01:00:00+03:00', end: '2026-10-10T03:00:00+03:00', "
              "reason: Maintenance, ticket: CHG-1, approver: noc-lead}\n")
        from tests.helpers import MINI
        base = MINI.replace("planned_downtime: []\n", "")
        now = datetime.datetime(2026, 10, 8, tzinfo=datetime.timezone.utc)
        self.assertEqual(self.errs(base + pd, now), [])
        self.assertTrue(any("ticket" in e for e in self.errs(base + pd.replace("ticket: CHG-1, ", ""), now)))
        self.assertTrue(any("approver" in e for e in self.errs(base + pd.replace(", approver: noc-lead", ""), now)))
        self.assertTrue(any("longer than" in e for e in self.errs(base + pd.replace("03:00:00", "23:00:00"), now)))
        info = [str(p) for p in self.v(base + pd.replace("2026-10-10", "2026-08-10"), now).infos]
        self.assertTrue(any("closed month" in e for e in info))
        self.assertEqual(self.errs(base + pd.replace("2026-10-10", "2026-08-10"), now), [])
        self.assertTrue(any("unknown sla class" in e for e in self.errs(base + pd.replace("[std]", "[nope]"), now)))

    def test_planned_downtime_becomes_excluded_downtime_on_the_sla(self):
        from tests.helpers import MINI
        base = MINI.replace("planned_downtime: []\n", "")
        pd = ("planned_downtime:\n  - {id: pd1, slas: [std], start: '2026-10-10T01:00:00+03:00', end: '2026-10-10T03:00:00+03:00', "
              "reason: Maintenance, ticket: CHG-1, approver: noc-lead}\n")
        d = model.compile_inventory(self.v(base + pd))
        self.assertEqual(len(d.slas["std"]["excluded_downtimes"]), 1)
        self.assertEqual(len(d.slas["ver"]["excluded_downtimes"]), 0)
        self.assertIn("CHG-1", d.slas["std"]["excluded_downtimes"][0]["name"])


if __name__ == "__main__":
    unittest.main()

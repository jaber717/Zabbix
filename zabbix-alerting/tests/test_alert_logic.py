"""Behavioural proofs on the *generated* trigger expressions (see zsim.py)."""
import unittest

from tests.zsim import InterfaceSim, evaluate, macros_for, resolve
from netalert import template as tpl

G = 10 ** 9   # 1 Gbit/s link


def cfg(**iface):
    base = {"description": "test link", "role": "ISP", "severity": "disaster",
            "utilization": {"enabled": True, "threshold": 70, "recovery": 65}}
    base.update(iface)
    return {"hosts": {"RTR-01": {"site": "HQ", "interfaces": {"Gi0/0": base}}}}


def sim(**iface):
    return InterfaceSim(macros_for(cfg(**iface)), "Gi0/0")


class Utilization(unittest.TestCase):
    def test_newest_sample_triggers_immediately_no_averaging(self):
        s = sim()
        for _ in range(30):                      # five minutes of idle at 10 s
            s.sample(10, rx=1000)
        self.assertFalse(s.problem("util_rx"))
        s.sample(10, rx=int(0.71 * G))           # ONE sample above 70 %
        self.assertTrue(s.problem("util_rx"))    # no avg/min window: fires on that very sample
        self.assertEqual(s.problems_opened("util_rx"), 1)

    def test_exactly_at_threshold_does_not_fire(self):
        s = sim()
        s.sample(10, rx=int(0.70 * G))
        self.assertFalse(s.problem("util_rx"))
        s.sample(10, rx=int(0.70 * G) + 1)
        self.assertTrue(s.problem("util_rx"))

    def test_recovery_hysteresis_holds_between_65_and_70(self):
        s = sim()
        s.sample(10, rx=int(0.80 * G))
        self.assertTrue(s.problem("util_rx"))
        for pct in (0.69, 0.66, 0.651, 0.67, 0.70):   # wobbling inside the dead band
            s.sample(10, rx=int(pct * G))
            self.assertTrue(s.problem("util_rx"), pct)
        s.sample(10, rx=int(0.649 * G))               # below recovery
        self.assertFalse(s.problem("util_rx"))
        self.assertEqual([e[2] for e in s.events if e[1] == "util_rx"], ["PROBLEM", "OK"])

    def test_oscillation_around_threshold_is_one_problem(self):
        s = sim()
        for pct in (0.71, 0.69, 0.72, 0.68, 0.73, 0.69, 0.71, 0.67):
            s.sample(10, rx=int(pct * G))
        self.assertEqual(s.problems_opened("util_rx"), 1)

    def test_rx_and_tx_are_independent(self):
        s = sim()
        s.sample(10, rx=int(0.9 * G), tx=1000)
        self.assertTrue(s.problem("util_rx"))
        self.assertFalse(s.problem("util_tx"))
        s.sample(10, rx=1000, tx=int(0.9 * G))
        self.assertFalse(s.problem("util_rx"))
        self.assertTrue(s.problem("util_tx"))

    def test_custom_threshold_and_recovery(self):
        s = InterfaceSim(macros_for(cfg(utilization={"enabled": True, "threshold": 90, "recovery": 80})), "Gi0/0")
        s.sample(10, rx=int(0.85 * G))
        self.assertFalse(s.problem("util_rx"))
        s.sample(10, rx=int(0.91 * G))
        self.assertTrue(s.problem("util_rx"))
        s.sample(10, rx=int(0.85 * G))
        self.assertTrue(s.problem("util_rx"))
        s.sample(10, rx=int(0.79 * G))
        self.assertFalse(s.problem("util_rx"))

    def test_disabled_utilization_never_fires(self):
        s = InterfaceSim(macros_for(cfg(utilization={"enabled": False})), "Gi0/0")
        s.sample(10, rx=G, tx=G)
        self.assertFalse(s.problem("util_rx") or s.problem("util_tx"))

    def test_zero_speed_does_not_divide_or_fire(self):
        s = sim()
        s.sample(10, rx=1000, speed=0)
        self.assertFalse(s.problem("util_rx"))

    def test_expected_speed_is_the_capacity(self):
        # 10G configured; ifHighSpeed says 1G (degraded). Capacity stays 10G (JS override in the item),
        # so 0.8 Gbit/s is 8 % and must NOT fire, while the speed trigger does.
        s = InterfaceSim(macros_for(cfg(expected_speed="10G")), "Gi0/0")
        s.sample(10, rx=int(0.8 * G), speed=10 * G, hspeed=1000)
        self.assertFalse(s.problem("util_rx"))
        self.assertTrue(s.problem("speed_degraded"))
        s.sample(10, rx=int(0.8 * G), speed=10 * G, hspeed=10000)
        self.assertFalse(s.problem("speed_degraded"))


class LinkState(unittest.TestCase):
    def test_down_on_first_bad_sample_and_up_on_first_good(self):
        s = sim()
        s.sample(10, oper=1)
        self.assertFalse(s.problem("link_down"))
        s.sample(10, oper=2)
        self.assertTrue(s.problem("link_down"))     # immediate: next poll, no delay window
        s.sample(10, oper=1)
        self.assertFalse(s.problem("link_down"))    # immediate UP
        self.assertEqual([e[2] for e in s.events if e[1] == "link_down"], ["PROBLEM", "OK"])

    def test_every_non_up_status_counts_as_down(self):
        for status in (2, 3, 5, 6, 7):
            s = sim()
            s.sample(10, oper=1)
            s.sample(10, oper=status)
            self.assertTrue(s.problem("link_down"), status)

    def test_link_alert_off(self):
        s = InterfaceSim(macros_for(cfg(link_alert=False)), "Gi0/0")
        s.sample(10, oper=1)
        s.sample(10, oper=2)
        self.assertFalse(s.problem("link_down"))

    def test_flapping_is_one_problem_and_suppresses_link_storm(self):
        s = sim()
        s.sample(10, oper=1)
        for i in range(24):                          # 24 transitions in four minutes
            s.sample(10, oper=2 if i % 2 == 0 else 1)
        self.assertEqual(s.problems_opened("flapping"), 1)
        # the first DOWN fired normally; everything after the flap detector opened is suppressed
        self.assertLessEqual(s.problems_opened("link_down"), 2)
        flap_at = [e[0] for e in s.events if e[1] == "flapping"][0]
        self.assertEqual([e for e in s.events if e[1] == "link_down" and e[0] > flap_at], [])

    def test_persistent_outage_after_flapping_still_alerts(self):
        s = sim()
        s.sample(10, oper=1)
        for i in range(8):
            s.sample(10, oper=2 if i % 2 == 0 else 1)
        s.sample(10, oper=2)                         # ends down
        for _ in range(40):                          # 20 minutes down, no more transitions
            s.sample(30, oper=2)
        self.assertFalse(s.problem("flapping"))      # window slid past the transitions
        self.assertTrue(s.problem("link_down"))      # and the real outage is now reported

    def test_flapping_threshold_is_configurable(self):
        s = InterfaceSim(macros_for(cfg(flapping={"enabled": True, "transitions": 6, "window": "10m"})), "Gi0/0")
        s.sample(10, oper=1)
        for i in range(4):
            s.sample(10, oper=2 if i % 2 == 0 else 1)
        self.assertFalse(s.problem("flapping"))
        for i in range(4):
            s.sample(10, oper=2 if i % 2 == 0 else 1)
        self.assertTrue(s.problem("flapping"))


class ErrorsAndDiscards(unittest.TestCase):
    def test_error_rate_with_recovery(self):
        s = InterfaceSim(macros_for(cfg(errors={"enabled": True, "rate": 5, "recovery": 1})), "Gi0/0")
        s.sample(10, ein=2)
        self.assertFalse(s.problem("errors"))
        s.sample(10, ein=6)
        self.assertTrue(s.problem("errors"))
        s.sample(10, ein=3)
        self.assertTrue(s.problem("errors"))         # still above recovery
        s.sample(10, ein=1)
        self.assertFalse(s.problem("errors"))

    def test_outbound_direction_counts(self):
        s = sim()
        s.sample(10, eout=3)
        self.assertTrue(s.problem("errors"))

    def test_discards_independent_of_errors(self):
        s = sim()
        s.sample(10, dout=10)
        self.assertTrue(s.problem("discards"))
        self.assertFalse(s.problem("errors"))

    def test_off_switches(self):
        s = InterfaceSim(macros_for(cfg(errors={"enabled": False}, discards={"enabled": False})), "Gi0/0")
        s.sample(10, ein=99, din=99)
        self.assertFalse(s.problem("errors") or s.problem("discards"))


class SeverityRouting(unittest.TestCase):
    def test_exactly_one_variant_is_active_per_interface(self):
        for name in ("warning", "average", "high", "disaster"):
            macros = macros_for(cfg(severity=name))
            s = InterfaceSim(macros, "Gi0/0")
            s.sample(10, oper=2)
            active = []
            for tp in tpl.trigger_prototypes():
                tags = dict((x["tag"], x["value"]) for x in tp["tags"])
                if tags["netops_alert"] == "link_down" and \
                        evaluate(resolve(tp["expression"], macros, "Gi0/0"), s.series, s.t):
                    active.append(tp["priority"])
            self.assertEqual(active, [name.upper()], name)

    def test_two_interfaces_two_severities(self):
        c = {"hosts": {"R": {"interfaces": {
            "A": {"description": "a", "severity": "warning"},
            "B": {"description": "b", "severity": "disaster"}}}}}
        macros = macros_for(c, host="R")
        a, b = InterfaceSim(macros, "A"), InterfaceSim(macros, "B")
        self.assertEqual(a.protos["link_down"]["priority"], "WARNING")
        self.assertEqual(b.protos["link_down"]["priority"], "DISASTER")


if __name__ == "__main__":
    unittest.main()

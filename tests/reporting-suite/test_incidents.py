import unittest
from datetime import date

from common import NOW, TZ
from zrs import incidents as I
from zrs import periods as P

DAY = P.day_period(date(2026, 10, 7), TZ)
S, E = DAY.start_ts, DAY.end_ts
H = 3600
PATTERNS = ["unavailable", "icmp ping"]
SITES = {"1": "HQ", "2": "BR", "3": "HQ"}


def ev(eid, start, r="0", hosts=("1",), name="Unavailable by ICMP ping", sev=4, ack="0"):
    return {"eventid": str(eid), "clock": str(start), "name": name, "severity": str(sev), "acknowledged": ack, "r_eventid": r,
            "hosts": [{"hostid": h, "name": "H" + h} for h in hosts]}


def build(events, recoveries=None, now=None):
    return I.build_incidents(events, recoveries or {}, DAY, now or NOW.timestamp(), PATTERNS, SITES)


class Reconstruction(unittest.TestCase):
    def test_resolved_inside_window(self):
        incs, q = build([ev(1, S + 10 * H, "91")], {"91": S + 11 * H})
        i = incs[0]
        self.assertTrue(i["started_in_window"] and i["resolved_in_window"] and not i["open_at_period_end"])
        self.assertEqual(i["duration_in_window_s"], H)
        self.assertEqual(i["duration_total_s"], H)

    def test_started_before_and_resolved_inside_is_clipped(self):
        incs, _ = build([ev(1, S - 5 * H, "91")], {"91": S + 2 * H})
        i = incs[0]
        self.assertFalse(i["started_in_window"])
        self.assertTrue(i["resolved_in_window"])
        self.assertEqual(i["duration_in_window_s"], 2 * H)           # clipped to the window
        self.assertEqual(i["duration_total_s"], 7 * H)               # full duration kept for MTTR

    def test_open_incident_runs_to_period_end_and_is_flagged(self):
        incs, _ = build([ev(1, S - 24 * H)])
        i = incs[0]
        self.assertTrue(i["open_at_period_end"])
        self.assertIsNone(i["end"])
        self.assertEqual(i["duration_in_window_s"], 86400)
        self.assertIsNone(i["duration_total_s"])

    def test_resolved_after_window_is_open_at_period_end(self):
        incs, _ = build([ev(1, S + 20 * H, "91")], {"91": E + 2 * H})
        self.assertTrue(incs[0]["open_at_period_end"])
        self.assertFalse(incs[0]["resolved_in_window"])
        self.assertEqual(incs[0]["duration_in_window_s"], 4 * H)

    def test_half_open_boundaries(self):
        # starts exactly at window end -> outside; ends exactly at window start -> outside
        incs, _ = build([ev(1, E, "91"), ev(2, S - H, "92"), ev(3, S, "93")], {"91": E + H, "92": S, "93": S + 60})
        self.assertEqual([i["eventid"] for i in incs], ["3"])
        self.assertTrue(incs[0]["started_in_window"])               # starting exactly at S is inside

    def test_duplicates_removed_and_counted(self):
        incs, q = build([ev(1, S + H, "91"), ev(1, S + H, "91")], {"91": S + 2 * H})
        self.assertEqual(len(incs), 1)
        self.assertEqual(q["duplicate_events_removed"], 1)

    def test_multi_host_event_is_one_incident_with_all_hosts_and_sites(self):
        incs, _ = build([ev(1, S + H, "91", hosts=("1", "2"))], {"91": S + 2 * H})
        self.assertEqual(len(incs), 1)
        self.assertEqual(incs[0]["sites"], ["BR", "HQ"])
        self.assertEqual(sorted(incs[0]["host_names"]), ["H1", "H2"])

    def test_unreadable_recovery_is_open_and_flagged_not_invented(self):
        incs, q = build([ev(1, S + H, "999")], {})
        self.assertIsNone(incs[0]["end"])
        self.assertTrue(incs[0]["recovery_time_unknown"])
        self.assertEqual(q["recovery_time_unknown"], 1)

    def test_downtime_class_from_patterns(self):
        incs, _ = build([ev(1, S + H, "91"), ev(2, S + H, "92", name="High CPU utilization")], {"91": S + 2 * H, "92": S + 2 * H})
        by = dict((i["eventid"], i["is_downtime"]) for i in incs)
        self.assertEqual(by, {"1": True, "2": False})

    def test_ordering_is_deterministic(self):
        incs, _ = build([ev(5, S + 2 * H, "95"), ev(4, S + H, "94"), ev(3, S + H, "93")], {"95": S + 3 * H, "94": S + 3 * H, "93": S + 3 * H})
        self.assertEqual([i["eventid"] for i in incs], ["3", "4", "5"])


class Downtime(unittest.TestCase):
    def test_union_of_overlapping_intervals(self):
        self.assertEqual(I.union_seconds([(0, 10), (5, 15), (20, 30)]), 25)
        self.assertEqual(I.union_seconds([(0, 10), (10, 20)]), 20)
        self.assertEqual(I.union_seconds([(5, 5), (7, 3)]), 0)
        self.assertEqual(I.union_seconds([]), 0)

    def test_overlapping_incidents_on_one_host_are_not_double_counted(self):
        incs, _ = build([ev(1, S + 10 * H, "91"), ev(2, S + 10 * H + 900, "92", name="Unavailable by ICMP ping")],
                        {"91": S + 10 * H + 1800, "92": S + 10 * H + 2700})
        self.assertEqual(I.host_downtime(incs, DAY, NOW.timestamp()), {"1": 2700})

    def test_downtime_is_per_host_for_multi_host_events(self):
        incs, _ = build([ev(1, S + H, "91", hosts=("1", "2"))], {"91": S + 2 * H})
        self.assertEqual(I.host_downtime(incs, DAY, NOW.timestamp()), {"1": H, "2": H})

    def test_non_downtime_class_does_not_count(self):
        incs, _ = build([ev(1, S + H, "91", name="High CPU utilization")], {"91": S + 2 * H})
        self.assertEqual(I.host_downtime(incs, DAY, NOW.timestamp()), {})

    def test_open_incident_counts_until_period_end_when_report_is_after(self):
        incs, _ = build([ev(1, S + 20 * H)])
        self.assertEqual(I.host_downtime(incs, DAY, NOW.timestamp()), {"1": 4 * H})

    def test_mttr_only_resolved_in_window_and_not_clipped(self):
        incs, _ = build([ev(1, S - 5 * H, "91"), ev(2, S + H, "92"), ev(3, S + 20 * H)],
                        {"91": S + 2 * H, "92": S + H + 600})
        self.assertEqual(I.mttr_seconds(incs), (7 * H + 600) / 2.0)
        self.assertIsNone(I.mttr_seconds([i for i in incs if i["eventid"] == "3"]))


if __name__ == "__main__":
    unittest.main()

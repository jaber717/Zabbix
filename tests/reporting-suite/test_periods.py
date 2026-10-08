import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from common import NOW, TZ
from zrs import periods as P


class Windows(unittest.TestCase):
    def test_daily_is_half_open_local_midnight(self):
        p = P.day_period(date(2026, 10, 7), TZ)
        self.assertEqual(p.start.isoformat(), "2026-10-07T00:00:00+03:00")
        self.assertEqual(p.end.isoformat(), "2026-10-08T00:00:00+03:00")
        self.assertEqual(p.seconds, 86400)
        self.assertTrue(p.contains(p.start_ts))
        self.assertFalse(p.contains(p.end_ts))              # end is exclusive
        self.assertEqual(p.last_query_ts, p.end_ts - 1)     # Zabbix time_till is inclusive

    def test_adjacent_periods_share_no_second(self):
        a = P.day_period(date(2026, 10, 7), TZ)
        b = P.day_period(date(2026, 10, 8), TZ)
        self.assertEqual(a.end_ts, b.start_ts)
        self.assertFalse(a.contains(b.start_ts))

    def test_week_starts_monday_and_sunday_option(self):
        thu = date(2026, 10, 8)
        w = P.week_period(thu, TZ)
        self.assertEqual((w.first_day, w.end_day), (date(2026, 10, 5), date(2026, 10, 12)))
        self.assertEqual(w.first_day.weekday(), 0)
        s = P.week_period(thu, TZ, week_start=6)
        self.assertEqual(s.first_day, date(2026, 10, 4))
        self.assertEqual(s.first_day.weekday(), 6)
        self.assertEqual(len(w.days()), 7)

    def test_week_label_is_iso(self):
        self.assertEqual(P.week_period(date(2026, 9, 30), TZ).label, "2026-W40")
        self.assertEqual(P.week_period(date(2026, 1, 1), TZ).label, "2026-W01")
        self.assertEqual(P.week_period(date(2027, 1, 1), TZ).label, "2026-W53")      # ISO year differs from calendar year

    def test_month_lengths_and_leap_year(self):
        self.assertEqual(P.month_period(2028, 2, TZ).seconds, 29 * 86400)
        self.assertEqual(P.month_period(2027, 2, TZ).seconds, 28 * 86400)
        self.assertEqual(P.month_period(2026, 9, TZ).seconds, 30 * 86400)
        self.assertEqual(P.month_period(2026, 10, TZ).label, "2026-10")

    def test_year_rollover(self):
        dec = P.month_period(2026, 12, TZ)
        self.assertEqual(dec.end.isoformat(), "2027-01-01T00:00:00+03:00")
        self.assertEqual(P.preceding(P.month_period(2027, 1, TZ)).label, "2026-12")
        prev = P.previous_complete("monthly", datetime(2027, 1, 1, 0, 0, tzinfo=TZ), TZ)
        self.assertEqual(prev.label, "2026-12")
        w = P.previous_complete("weekly", datetime(2027, 1, 4, 9, 0, tzinfo=TZ), TZ)      # Monday
        self.assertEqual((w.first_day, w.end_day), (date(2026, 12, 28), date(2027, 1, 4)))

    def test_previous_complete_exactly_at_boundary(self):
        # at 00:00:00 of the 8th the 7th has just completed
        self.assertEqual(P.previous_complete("daily", datetime(2026, 10, 8, 0, 0, tzinfo=TZ), TZ).label, "2026-10-07")
        # one second earlier it has not
        self.assertEqual(P.previous_complete("daily", datetime(2026, 10, 7, 23, 59, 59, tzinfo=TZ), TZ).label, "2026-10-06")
        self.assertEqual(P.previous_complete("daily", NOW, TZ).label, "2026-10-07")

    def test_previous_complete_uses_local_date_not_utc(self):
        # 2026-10-08 01:00 +03 is still 2026-10-07 22:00 UTC; the LOCAL day is the 8th
        now = datetime(2026, 10, 8, 1, 0, tzinfo=TZ)
        self.assertEqual(P.previous_complete("daily", now.astimezone(ZoneInfo("UTC")), TZ).label, "2026-10-07")

    def test_weekly_and_monthly_previous(self):
        self.assertEqual(P.previous_complete("weekly", NOW, TZ).label, "2026-W40")
        self.assertEqual(P.previous_complete("monthly", NOW, TZ).label, "2026-09")

    def test_dst_days_have_exact_lengths(self):
        ny = ZoneInfo("America/New_York")
        self.assertEqual(P.day_period(date(2026, 3, 8), ny).seconds, 23 * 3600)         # spring forward
        self.assertEqual(P.day_period(date(2026, 11, 1), ny).seconds, 25 * 3600)        # fall back
        self.assertEqual(P.week_period(date(2026, 3, 5), ny).seconds, 7 * 86400 - 3600)       # the week containing the change
        self.assertEqual(P.week_period(date(2026, 3, 12), ny).seconds, 7 * 86400)
        self.assertEqual(sum(d.seconds for d in P.week_period(date(2026, 3, 5), ny).days()), P.week_period(date(2026, 3, 5), ny).seconds)

    def test_preceding_same_kind(self):
        m = P.month_period(2026, 3, TZ)
        self.assertEqual(P.preceding(m).label, "2026-02")
        w = P.week_period(date(2026, 10, 8), TZ)
        self.assertEqual(P.preceding(w).label, "2026-W40")

    def test_unknown_kind(self):
        with self.assertRaises(ValueError):
            P.containing("hourly", date(2026, 1, 1), TZ)


if __name__ == "__main__":
    unittest.main()

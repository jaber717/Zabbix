"""Reporting periods: half-open [start, end) windows on local calendar boundaries."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

KINDS = ("daily", "weekly", "monthly")


def local_midnight(d, tz):
    """00:00 local on calendar date d (built from the date, never by adding 24 h to an instant)."""
    return datetime.combine(d, time(0, 0), tzinfo=tz)


class Period(object):
    def __init__(self, kind, first_day, last_day_exclusive, tz):
        self.kind = kind
        self.tz = tz
        self.first_day = first_day
        self.end_day = last_day_exclusive          # exclusive calendar date
        self.start = local_midnight(first_day, tz)
        self.end = local_midnight(last_day_exclusive, tz)

    @property
    def start_ts(self):
        return int(self.start.timestamp())

    @property
    def end_ts(self):
        """Exclusive. Zabbix `time_till` is inclusive, so queries must use end_ts - 1."""
        return int(self.end.timestamp())

    @property
    def seconds(self):
        return self.end_ts - self.start_ts

    @property
    def last_query_ts(self):
        return self.end_ts - 1

    def contains(self, ts):
        return self.start_ts <= ts < self.end_ts

    def days(self):
        """Calendar-day sub-periods (a day is 23/25 h across a DST change; seconds are exact)."""
        out, d = [], self.first_day
        while d < self.end_day:
            out.append(Period("daily", d, d + timedelta(days=1), self.tz))
            d += timedelta(days=1)
        return out

    @property
    def label(self):
        if self.kind == "daily":
            return self.first_day.isoformat()
        if self.kind == "weekly":
            iso = self.first_day.isocalendar()
            return "%d-W%02d" % (iso[0], iso[1])
        return "%04d-%02d" % (self.first_day.year, self.first_day.month)

    def to_dict(self):
        return {"kind": self.kind, "label": self.label, "timezone": str(self.tz),
                "start": self.start.isoformat(), "end": self.end.isoformat(),
                "start_ts": self.start_ts, "end_ts": self.end_ts, "seconds": self.seconds,
                "boundaries": "half-open [start, end)"}


def day_period(d, tz):
    return Period("daily", d, d + timedelta(days=1), tz)


def week_period(d, tz, week_start=0):
    """The week (default Monday..Sunday, ISO) containing calendar date d."""
    first = d - timedelta(days=(d.weekday() - week_start) % 7)
    return Period("weekly", first, first + timedelta(days=7), tz)


def month_period(year, month, tz):
    first = date(year, month, 1)
    nxt = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return Period("monthly", first, nxt, tz)


def containing(kind, d, tz, week_start=0):
    if kind == "daily":
        return day_period(d, tz)
    if kind == "weekly":
        return week_period(d, tz, week_start)
    if kind == "monthly":
        return month_period(d.year, d.month, tz)
    raise ValueError("unknown period kind %r" % (kind,))


def previous_complete(kind, now, tz, week_start=0):
    """The most recent period that has fully ended before `now` (an aware datetime)."""
    today = now.astimezone(tz).date()
    cur = containing(kind, today, tz, week_start)
    return containing(kind, cur.first_day - timedelta(days=1), tz, week_start)


def preceding(period, week_start=0):
    """The period of the same kind immediately before `period` (month-over-month, week-over-week)."""
    return containing(period.kind, period.first_day - timedelta(days=1), period.tz, week_start)

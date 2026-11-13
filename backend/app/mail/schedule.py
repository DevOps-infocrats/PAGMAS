"""When a schedule runs. Pure functions (no database, no clock) so every rule is unit-testable.

  * Times are wall-clock times in MAIL_TIMEZONE (default Asia/Kolkata); stored and compared in UTC.
  * daily    every day at send_time, from start_date on
  * weekly   on `weekday` (0 = Monday … 6 = Sunday) at send_time, from start_date on
  * monthly  on `month_day` (1–31) at send_time; in a shorter month on its last day (31 -> 30 Apr, 28/29 Feb)
  * The next run is always strictly after "now": creating, editing or enabling a schedule never makes it due at once.
  * Missed runs (server down at the time): still sent when seen within MISSED_GRACE of the planned time; an older one
    is recorded as SKIPPED and the schedule moves on. Missed runs never pile up into several e-mails.
"""

from __future__ import annotations

import calendar
import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

FREQUENCIES = ("daily", "weekly", "monthly")
MISSED_GRACE = dt.timedelta(hours=6)
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


class ScheduleError(ValueError):
    pass


@dataclass(frozen=True)
class Schedule:
    frequency: str
    start_date: dt.date
    send_time: str  # "HH:MM"
    weekday: int | None = None
    month_day: int | None = None


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ScheduleError(f"Unknown timezone {name!r} (MAIL_TIMEZONE)") from None


def parse_time(value: str) -> dt.time:
    try:
        h, m = value.split(":")
        if len(h) != 2 or len(m) != 2:
            raise ValueError
        return dt.time(int(h), int(m))
    except (ValueError, AttributeError):
        raise ScheduleError("Send time must be HH:MM (24-hour), e.g. 09:30") from None


def validate(s: Schedule) -> Schedule:
    """The schedule with fields that do not apply cleared; raises ScheduleError for an invalid one."""
    if s.frequency not in FREQUENCIES:
        raise ScheduleError(f"Frequency must be one of {', '.join(FREQUENCIES)}")
    parse_time(s.send_time)
    if not dt.date(2020, 1, 1) <= s.start_date <= dt.date(2100, 12, 31):
        raise ScheduleError("Start date is out of range")
    weekday, month_day = None, None
    if s.frequency == "weekly":
        if s.weekday is None or not 0 <= s.weekday <= 6:
            raise ScheduleError("A weekly schedule needs a day of the week (0 = Monday … 6 = Sunday)")
        weekday = s.weekday
    if s.frequency == "monthly":
        if s.month_day is None or not 1 <= s.month_day <= 31:
            raise ScheduleError("A monthly schedule needs a day of the month between 1 and 31")
        month_day = s.month_day
    return Schedule(s.frequency, s.start_date, s.send_time, weekday, month_day)


def _matches(s: Schedule, d: dt.date) -> bool:
    if s.frequency == "daily":
        return True
    if s.frequency == "weekly":
        return d.weekday() == s.weekday
    last = calendar.monthrange(d.year, d.month)[1]
    return d.day == min(s.month_day or 1, last)


def next_run(s: Schedule, after: dt.datetime, tz: str) -> dt.datetime:
    """First run time strictly after `after` (aware), as an aware UTC datetime."""
    if after.tzinfo is None:
        raise ValueError("`after` must be timezone-aware")
    s = validate(s)
    z = zone(tz)
    at = parse_time(s.send_time)
    d = max(s.start_date, after.astimezone(z).date())
    for _ in range(400):  # a monthly schedule matches within 31 days
        if _matches(s, d):
            when = dt.datetime.combine(d, at, tzinfo=z)
            if when > after:
                return when.astimezone(dt.UTC)
        d += dt.timedelta(days=1)
    raise ScheduleError("No run time found")  # pragma: no cover - unreachable for valid schedules


def describe(s: Schedule) -> str:
    if s.frequency == "daily":
        return f"Every day at {s.send_time}"
    if s.frequency == "weekly":
        return f"Every {WEEKDAYS[s.weekday or 0]} at {s.send_time}"
    return f"Monthly on day {s.month_day} at {s.send_time}" + (" (last day in shorter months)" if (s.month_day or 0) > 28 else "")

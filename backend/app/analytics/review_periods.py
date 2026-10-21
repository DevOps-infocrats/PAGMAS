"""Reporting-period rules for the Management Review (reused by every page).

Nothing here is hard-coded to a week or month: everything is derived from the active
dataset's own weeks (W-nn columns, Fri–Thu) and its last data date.

Rules
  * Completed week  = a source week whose end date is on or before the file's data-as-of date.
    The default reporting week is the latest completed week; its comparison week is the one
    immediately before it.
  * Month cutoff D  = the last date with data, capped at the reporting week's end.
  * Month windows   = day 1 .. day D of the cutoff month vs day 1 .. the same day number of the
    previous month (a shorter previous month stops on its last day). Days missing from the
    daily sheet are skipped and reported.
"""

from __future__ import annotations

import calendar
import datetime as dt
from dataclasses import dataclass, field

from .store import Store, Week


def latest_completed_week(store: Store) -> Week | None:
    done = [w for w in store.weeks if w.end <= store.data_as_of]
    return done[-1] if done else None


def previous_week(store: Store, week: Week) -> Week | None:
    i = [w.code for w in store.weeks].index(week.code)
    return store.weeks[i - 1] if i > 0 else None


def month_window(cutoff: dt.date, months_back: int) -> tuple[dt.date, dt.date]:
    """Day 1 .. same day number as `cutoff`, `months_back` months earlier (clamped to month end)."""
    y, m = cutoff.year, cutoff.month - months_back
    while m < 1:
        y, m = y - 1, m + 12
    return dt.date(y, m, 1), dt.date(y, m, min(cutoff.day, calendar.monthrange(y, m)[1]))


def window_label(start: dt.date, end: dt.date) -> str:
    """"1–8 Oct 2026", or "25 Sep – 1 Oct 2026" when the range crosses a month."""
    if start == end:
        return f"{start.day} {start:%b %Y}"
    if (start.year, start.month) != (end.year, end.month):
        return f"{start.day} {start:%b} – {end.day} {end:%b %Y}"
    return f"{start.day}–{end.day} {start:%b %Y}"


def week_label(w: Week) -> str:
    return f"WK-{w.number} ({w.start:%d %b} – {w.end:%d %b %Y})"


@dataclass
class ReportingPeriods:
    week: Week
    compare: Week
    cutoff: dt.date
    month: tuple[dt.date, dt.date]
    previous_month: tuple[dt.date, dt.date]
    week_complete: bool = True
    warnings: list[str] = field(default_factory=list)

    def as_json(self) -> dict:
        def rng(a: dt.date, b: dt.date) -> dict:
            return {"start": a.isoformat(), "end": b.isoformat(), "range": window_label(a, b)}

        return {
            "week": {**rng(self.week.start, self.week.end), "id": self.week.code, "number": self.week.number, "label": f"WK-{self.week.number}", "title": week_label(self.week), "complete": self.week_complete},
            "compareWeek": {**rng(self.compare.start, self.compare.end), "id": self.compare.code, "number": self.compare.number, "label": f"WK-{self.compare.number}", "title": week_label(self.compare)},
            "cutoff": self.cutoff.isoformat(),
            "month": rng(*self.month),
            "previousMonth": rng(*self.previous_month),
            "warnings": self.warnings,
        }


def reporting_periods(store: Store, week: Week, compare: Week) -> ReportingPeriods:
    warnings: list[str] = []
    if week.end > store.data_as_of:
        warnings.append(
            f"WK-{week.number} is not complete: data runs to {store.data_as_of:%d %b %Y}, the week ends {week.end:%d %b %Y}. "
            "Its figures cover a partial week."
        )
    prev = previous_week(store, week)
    if prev is None or prev.code != compare.code:
        warnings.append(f"Comparison week WK-{compare.number} is not the week immediately before WK-{week.number}.")
    cutoff = min(week.end, store.data_as_of)
    cur_m, prev_m = month_window(cutoff, 0), month_window(cutoff, 1)
    days = set(store.daily.columns)
    for a, b in (cur_m, prev_m):
        missing = [a + dt.timedelta(days=i) for i in range((b - a).days + 1) if a + dt.timedelta(days=i) not in days]
        if missing:
            shown = ", ".join(f"{d:%d %b}" for d in missing[:6]) + (" …" if len(missing) > 6 else "")
            warnings.append(f"Daily data missing for {len(missing)} day(s) of {window_label(a, b)} ({shown}); those days are skipped.")
    return ReportingPeriods(week, compare, cutoff, cur_m, prev_m, week.end <= store.data_as_of, warnings)

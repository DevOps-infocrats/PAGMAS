"""Week calendar: the weeks run on the sheet's own week days (the day its W-nn labels start on – Fri–Thu labels give
Fri–Thu weeks, Sat–Fri labels give Sat–Fri weeks), every day is in exactly one week, and every week's availability is
checked against the daily values (recomputed and flagged when the sheet is wrong)."""

import datetime as dt

from app.ingestion.parser import ParsedWorkbook, _normalize_weeks

D = dt.date


def _book(weeks, weekly, daily, data_as_of=D(2026, 10, 30), amc=D(2026, 1, 1)):
    """weeks: [(code, start, end)]; weekly: {code: {gp: value}}; daily: {gp: {date: value}}."""
    out = ParsedWorkbook()
    out.data_as_of = data_as_of
    gps = sorted({*daily, *(g for w in weekly.values() for g in w)})
    out.gps = [{"gp_code": g, "amc_date": amc} for g in gps]
    out.weeks = [{"code": c, "number": int(c[2:]), "start_date": s, "end_date": e} for c, s, e in weeks]
    for code, vals in weekly.items():
        out.availability += [(g, "W", code, v) for g, v in vals.items()]
    for g, days in daily.items():
        out.availability += [(g, "D", d.isoformat(), v) for d, v in days.items()]
    return out


def _daily(start, end, value):
    n = (end - start).days + 1
    return {start + dt.timedelta(days=i): value(i) for i in range(n)}


def _weekly(out):
    res = {}
    for g, kind, code, v in out.availability:
        if kind == "W":
            res.setdefault(code, {})[g] = round(v, 4)
    return res


def _codes(out, prefix="WEEK"):
    return [i.code for i in out.issues if i.code.startswith(prefix)]


# GP "a": daily = day number (1, 2, 3 …) from 1 Oct; mean of a Fri–Thu week is easy to check.
DAILY = {"a": _daily(D(2026, 10, 1), D(2026, 10, 30), lambda i: float(i + 1))}
FRI_WEEKS = [("W-41", D(2026, 10, 2), D(2026, 10, 8)), ("W-42", D(2026, 10, 9), D(2026, 10, 15)), ("W-43", D(2026, 10, 16), D(2026, 10, 22))]
# day numbers: 2 Oct = 2 … so W-41 mean = (2..8)/7 = 5, W-42 = 12, W-43 = 19
RIGHT = {"W-41": {"a": 5.0}, "W-42": {"a": 12.0}, "W-43": {"a": 19.0}}


def test_correct_file_is_left_alone():
    out = _book(FRI_WEEKS, RIGHT, DAILY)
    _normalize_weeks(out)
    assert [(w["code"], w["start_date"], w["end_date"]) for w in out.weeks] == FRI_WEEKS
    assert _weekly(out) == RIGHT and _codes(out) == []


def test_sat_fri_sheet_keeps_its_own_weeks():
    """A sheet whose weeks run Saturday – Friday (the 03-11-26 file: W-45 = Sat 31 Oct – Fri 06 Nov) keeps those dates;
    its values computed on the same days are kept without any note."""
    sat = [(c, s + dt.timedelta(days=1), e + dt.timedelta(days=1)) for c, s, e in FRI_WEEKS]
    right = {"W-41": {"a": 6.0}, "W-42": {"a": 13.0}, "W-43": {"a": 20.0}}  # means of 3..9, 10..16, 17..23 Oct
    out = _book(sat, right, DAILY)
    _normalize_weeks(out)
    assert [(w["code"], w["start_date"], w["end_date"]) for w in out.weeks] == sat
    assert all(w["start_date"].weekday() == 5 and w["end_date"].weekday() == 4 for w in out.weeks)
    assert _weekly(out) == right and _codes(out) == []


def test_sat_fri_labels_with_fri_thu_values_are_recomputed():
    """Sat–Fri labels but values computed on Fri–Thu (the 01-11-26 sheet): the labelled days win, values recomputed."""
    sat = [(c, s + dt.timedelta(days=1), e + dt.timedelta(days=1)) for c, s, e in FRI_WEEKS]
    out = _book(sat, RIGHT, DAILY)
    _normalize_weeks(out)
    assert [(w["code"], w["start_date"], w["end_date"]) for w in out.weeks] == sat
    assert _weekly(out) == {"W-41": {"a": 6.0}, "W-42": {"a": 13.0}, "W-43": {"a": 20.0}}
    assert _codes(out) == ["WEEK_RECOMPUTED"] * 3


def test_one_label_off_the_rhythm_moves_to_it():
    """Most labels start on Friday, one on Saturday: that one moves to the Fri–Thu week (every day in one week)."""
    weeks = [FRI_WEEKS[0], FRI_WEEKS[1], ("W-43", D(2026, 10, 17), D(2026, 10, 23))]
    out = _book(weeks, RIGHT, DAILY)
    _normalize_weeks(out)
    assert [(w["code"], w["start_date"], w["end_date"]) for w in out.weeks] == FRI_WEEKS
    assert _codes(out) == ["WEEK_RANGE"]


def test_wrong_values_are_recomputed_and_flagged():
    """The sheet's W-42 left out 15 Oct (mean of 9–14 Oct = 11.5): the dashboard uses the full week and warns."""
    wrong = {**RIGHT, "W-42": {"a": 11.5}}
    out = _book(FRI_WEEKS, wrong, DAILY)
    _normalize_weeks(out)
    assert _weekly(out)["W-42"] == {"a": 12.0}
    issue = next(i for i in out.issues if i.code == "WEEK_RECOMPUTED")
    assert "W-42" in issue.message and "11.50%" in issue.message and "12.00%" in issue.message


def test_skipped_week_is_added():
    """A file without W-42: the gap is filled with a Fri–Thu W-42 computed from the daily values."""
    out = _book([FRI_WEEKS[0], FRI_WEEKS[2]], {"W-41": RIGHT["W-41"], "W-43": RIGHT["W-43"]}, DAILY)
    _normalize_weeks(out)
    assert [w["code"] for w in out.weeks] == ["W-41", "W-42", "W-43"]
    assert _weekly(out)["W-42"] == {"a": 12.0}
    days = [w["start_date"] + dt.timedelta(days=i) for w in out.weeks for i in range(7)]
    assert days == sorted(set(days)) and len(days) == 21  # every day in exactly one week


def test_week_before_daily_data_keeps_the_file_value():
    weeks = [("W-40", D(2026, 9, 25), D(2026, 10, 1)), *FRI_WEEKS]
    out = _book(weeks, {"W-40": {"a": 77.0}, **RIGHT}, DAILY)
    _normalize_weeks(out)
    assert _weekly(out)["W-40"] == {"a": 77.0} and _codes(out) == []


def test_partial_last_week_counts_up_to_the_data_date():
    weeks = [*FRI_WEEKS, ("W-44", D(2026, 10, 24), D(2026, 10, 30))]  # Sat–Fri label, data to 30 Oct
    out = _book(weeks, {**RIGHT, "W-44": {"a": 27.0}}, DAILY)  # sheet: mean of 24–30 Oct
    _normalize_weeks(out)
    assert out.weeks[-1]["start_date"] == D(2026, 10, 23) and out.weeks[-1]["end_date"] == D(2026, 10, 29)
    assert _weekly(out)["W-44"] == {"a": 26.0}  # 23–29 Oct
    assert "WEEK_RECOMPUTED" in _codes(out)


def test_gp_not_under_amc_by_week_end_is_ignored():
    out = _book(FRI_WEEKS, {"W-41": {}, "W-42": {}, "W-43": RIGHT["W-43"]}, DAILY, amc=D(2026, 10, 16))
    _normalize_weeks(out)
    assert _codes(out) == [] and _weekly(out).get("W-43") == RIGHT["W-43"]


def test_real_file_weeks_cover_every_day(imported):
    """The imported workbook's weeks run on one start day, consecutive, with distinct codes (no week the dashboard invents)."""
    ws = imported.weeks
    assert len({w.start.weekday() for w in ws}) == 1 and all((w.end - w.start).days == 6 for w in ws)
    assert all(b.start == a.end + dt.timedelta(days=1) for a, b in zip(ws, ws[1:]))
    assert len({w.code for w in ws}) == len(ws)

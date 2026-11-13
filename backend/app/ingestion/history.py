"""Daily availability history across uploads (models.GpDailyHistory).

merge_daily() is called by every import (inside its transaction) and by `app.cli backfill-daily`.
history_frame() gives the store the days the active file no longer carries.
"""

from __future__ import annotations

import datetime as dt
import json
import logging

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import GpDailyHistory
from .packs import pack, unpack
from .workbook import clean_code

log = logging.getLogger(__name__)
KEEP_MONTHS = 4  # months of history kept before the newest merged month (enough for "previous month to date")


def _recode(frame: pd.DataFrame) -> pd.DataFrame:
    """GP codes of packs written before codes were cleaned ('O033977' -> '0033977'); the later row wins on a clash."""
    codes = [clean_code(c) or c for c in frame.index]
    if codes == list(frame.index):
        return frame
    frame.index = pd.Index(codes, name=frame.index.name)
    return frame[~frame.index.duplicated(keep="last")]


def merge_daily(db: Session, daily: pd.DataFrame, data_as_of: dt.date, source_file: str) -> list[str]:
    """Merge a file's daily frame (gp_code × ISO date) into the monthly history packs; returns the months touched.

    A day present in both keeps the value of the file with the LATER data date (re-uploading an older file never
    overwrites newer values – it only fills days the history does not have yet). NaN (NA in the source) is a value
    like any other and is never replaced by an older number."""
    if daily is None or daily.empty:
        return []
    daily = daily.copy()
    daily.columns = [str(c) for c in daily.columns]
    months = sorted({c[:7] for c in daily.columns})
    for month in months:
        new = daily[[c for c in daily.columns if c[:7] == month]]
        row = db.get(GpDailyHistory, month)
        if row is None:
            merged, as_of = new, data_as_of
        else:
            old = _recode(unpack(row.gp_codes, row.periods, row.values))
            newer = data_as_of >= row.data_as_of
            idx = old.index.union(new.index)
            cols = sorted(set(old.columns) | set(new.columns))
            merged = old.reindex(index=idx, columns=cols)
            take = list(new.columns) if newer else [c for c in new.columns if c not in old.columns]
            if take:
                merged.loc[new.index, take] = new[take].to_numpy()
            as_of = max(data_as_of, row.data_as_of)
            if take:  # remember every file that supplied days to this month
                names = [n for n in row.source_file.split("; ") if n]
                source_file = "; ".join(names + ([source_file] if source_file not in names else []))
            else:
                source_file = row.source_file
            db.delete(row)
            db.flush()
        p = pack(0, "D", merged.sort_index().sort_index(axis=1))
        db.add(GpDailyHistory(month=month, gp_codes=p["gp_codes"], periods=p["periods"], values=p["values"], data_as_of=as_of, source_file=source_file[:255]))
    db.flush()
    # keep only the last KEEP_MONTHS months before the newest one
    all_months = sorted(db.scalars(select(GpDailyHistory.month)).all())
    if len(all_months) > KEEP_MONTHS + 1:
        db.execute(delete(GpDailyHistory).where(GpDailyHistory.month.in_(all_months[: -(KEEP_MONTHS + 1)])))
    return months


def history_frame(db: Session, before: dt.date) -> pd.DataFrame:
    """Daily values (gp_code × date) of the history for the days BEFORE `before` (the active file's first day)."""
    frames = []
    for row in db.scalars(select(GpDailyHistory).where(GpDailyHistory.month <= f"{before:%Y-%m}")):
        f = _recode(unpack(row.gp_codes, row.periods, row.values))
        f.columns = [dt.date.fromisoformat(c) for c in f.columns]
        keep = [c for c in f.columns if c < before]
        if keep:
            frames.append(f[keep])
    if not frames:
        return pd.DataFrame(dtype=float)
    out = pd.concat(frames, axis=1)
    return out.loc[:, ~out.columns.duplicated()].sort_index(axis=1)


def history_months(db: Session) -> list[dict]:
    return [
        {"month": r.month, "days": len(json.loads(r.periods)), "dataAsOf": r.data_as_of.isoformat(), "sourceFile": r.source_file}
        for r in db.scalars(select(GpDailyHistory).order_by(GpDailyHistory.month))
    ]


# ---------------------------------------------------------------- weekly / monthly history (models.PeriodHistory)
# Why: the daily file may start later than the previous one (W-45 onwards, only November). Without this, the weeks and
# months it dropped would vanish from the dashboard. Same rule as the daily history: a period in both keeps the values
# of the file with the later data date; an older file only fills periods the history does not have.

GP_PERIOD_KINDS = ("W", "M", "MA")  # GP Wise Data: weekly, monthly, monthly AMC GPs
BLOCK_PERIOD_KINDS = ("BW", "BM", "BMA", "BD")  # Master Block: weekly, monthly ALL GPs, monthly AMC GPs, daily


def _month_span(period: str) -> tuple[dt.date, dt.date]:
    y, m = int(period[:4]), int(period[5:7])
    start = dt.date(y, m, 1)
    return start, (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1))


def _block_week(code: str, weeks: dict[str, dict]) -> tuple[dt.date | None, dt.date | None, int]:
    """Dates of a Master Block week ("W-45"): the GP sheet's week of that number, else continued in 7-day steps."""
    number = int(code[2:])
    if code in weeks:
        return weeks[code]["start_date"], weeks[code]["end_date"], number
    if not weeks:
        return None, None, number
    last = max(weeks.values(), key=lambda w: w["end_date"])
    back = (last["number"] - number) % 52
    start = last["start_date"] - dt.timedelta(days=7 * back)
    return start, start + dt.timedelta(days=6), number


def _period_frames(parsed) -> dict[str, pd.DataFrame]:
    from .packs import wide_frames

    frames = {k: f for k, f in wide_frames(parsed.availability).items() if k in GP_PERIOD_KINDS}
    rows = getattr(parsed, "block_availability", None) or []
    if rows:
        long = pd.DataFrame(rows, columns=["code", "kind", "period", "value"])
        for kind in BLOCK_PERIOD_KINDS:
            part = long[long["kind"] == kind]
            if not part.empty:
                frames[kind] = part.pivot_table(index="code", columns="period", values="value", aggfunc="first").astype(float)
    return frames


def merge_periods(db: Session, parsed, source_file: str) -> dict[str, list[str]]:
    """Merge a parsed file's weekly / monthly (and Master Block) periods into the history, inside the import's
    transaction. Returns {"added": [...], "updated": [...], "kept": [...]} ("W-46", "M 2026-11" …) for the log."""
    from ..config import get_settings
    from ..models import PeriodHistory

    as_of = parsed.data_as_of
    out: dict[str, list[str]] = {"added": [], "updated": [], "kept": []}
    if as_of is None:
        return out
    weeks = {w["code"]: w for w in parsed.weeks}
    for kind, frame in _period_frames(parsed).items():
        for period in frame.columns:
            col = frame[[period]].dropna()
            if kind in ("W", "BW"):
                if kind == "W":
                    w = weeks.get(str(period))
                    if w is None:
                        continue
                    start, end, number = w["start_date"], w["end_date"], w["number"]
                else:
                    start, end, number = _block_week(str(period), weeks)
            elif kind == "BD":
                start = end = dt.date.fromisoformat(str(period))
                number = None
            else:
                start, end = _month_span(str(period))
                number = None
            label = f"{kind} {period}"
            row = db.get(PeriodHistory, (kind, str(period)))
            same_period = row is not None and (row.start_date is None or start is None or abs((row.start_date - start).days) < 180)
            if row is not None and same_period and row.data_as_of > as_of:
                out["kept"].append(label)  # an older file never overwrites newer values
                continue
            p = pack(0, kind, col)
            if row is None:
                db.add(PeriodHistory(kind=kind, period=str(period), start_date=start, end_date=end, number=number, codes=p["gp_codes"], values=p["values"], data_as_of=as_of, source_file=source_file[:255]))
                out["added"].append(label)
            else:
                row.start_date, row.end_date, row.number = start, end, number
                row.codes, row.values, row.data_as_of, row.source_file = p["gp_codes"], p["values"], as_of, source_file[:255]
                out["updated"].append(label)
    db.flush()
    # keep the last PERIOD_HISTORY_MONTHS months before the newest data date
    newest = max([as_of] + list(db.scalars(select(PeriodHistory.data_as_of))))
    cutoff = newest - dt.timedelta(days=31 * get_settings().period_history_months)
    db.execute(delete(PeriodHistory).where(PeriodHistory.end_date.is_not(None), PeriodHistory.end_date < cutoff))
    return out


def earlier_periods(db: Session, kind: str, have: set[str], before: dt.date | None = None, upto: dt.date | None = None) -> list[tuple[str, int | None, dt.date | None, dt.date | None, pd.Series, str]]:
    """History periods of `kind` the active file does not carry: (period, number, start, end, values, source file).
    `have` = the file's own periods (they always win); `before` = only periods ending before this date (weeks: the
    file's first week, so the calendar never overlaps); `upto` = never a period starting after the data date.

    Weeks: only those on the file's own 7-day rhythm (`before` = the file's first week start, so a whole number of
    weeks before it). An older file with other week days (e.g. Friday - Thursday, while the current file runs Saturday -
    Friday) would leave a day in no week and move every date-to-week lookup – such weeks are left out, never mixed."""
    from ..models import PeriodHistory

    out = []
    for r in db.scalars(select(PeriodHistory).where(PeriodHistory.kind == kind).order_by(PeriodHistory.start_date)):
        if r.period in have or (before is not None and (r.end_date is None or r.end_date >= before)) or (upto is not None and r.start_date is not None and r.start_date > upto):
            continue
        if kind in ("W", "BW") and before is not None and (r.start_date is None or (before - r.start_date).days % 7 != 0):
            continue  # another week calendar than the file's
        f = _recode(unpack(r.codes, json.dumps([r.period]), r.values))
        out.append((r.period, r.number, r.start_date, r.end_date, f[r.period], r.source_file))
    return out


def period_history_summary(db: Session) -> list[dict]:
    """What the weekly / monthly history holds (Data Operations)."""
    from ..models import PeriodHistory

    return [
        {"kind": r.kind, "period": r.period, "start": r.start_date.isoformat() if r.start_date else None, "end": r.end_date.isoformat() if r.end_date else None, "dataAsOf": r.data_as_of.isoformat(), "sourceFile": r.source_file}
        for r in db.scalars(select(PeriodHistory).order_by(PeriodHistory.kind, PeriodHistory.start_date))
    ]

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

log = logging.getLogger(__name__)
KEEP_MONTHS = 4  # months of history kept before the newest merged month (enough for "previous month to date")


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
            old = unpack(row.gp_codes, row.periods, row.values)
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
        f = unpack(row.gp_codes, row.periods, row.values)
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

"""In-memory analytical snapshot of the active dataset.

The active dataset (~16k GPs) is loaded once into pandas/numpy and reused for
every request. After a new import the next snapshot is built in the background
and swapped in (requests keep using the previous one meanwhile). A dataset
activated by another process (CLI import) is noticed within CHECK_EVERY_S.
Computed API payloads are memoised on the snapshot, so they are dropped with it.
"""

from __future__ import annotations

import datetime as dt
import re
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any, TypeVar

import numpy as np
import pandas as pd
from sqlalchemy import insert, select, text

from ..db import SessionLocal, engine
from ..ingestion.history import history_frame
from ..ingestion.packs import KINDS, pack, unpack, wide_frames
from ..models import Dataset, DatasetWeek, GpAmcPlan, GpAvailabilityPack, MasterBlock, ReportedNumber

log = logging.getLogger(__name__)
T = TypeVar("T")
MEMO_MAX = 256  # computed payloads kept per snapshot (overview / circle / block pages, reconciliation …)
WEEKS_PER_YEAR = 52
CHECK_EVERY_S = 30.0  # how often a request checks whether another process activated a new dataset
RETRY_AFTER_S = 10.0  # back-off after a failed snapshot load

CIRCLE_CODES = {"RAJASTHAN": "RJ", "HARYANA": "HR", "ASSAM": "AS"}


class NoDataError(Exception):
    pass


def slug(text_: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text_.lower()).strip("-") or "na"


def circle_id(name: str) -> str:
    return slug(name)


def circle_code(name: str) -> str:
    return CIRCLE_CODES.get(name.upper(), name[:2].upper())


def lifecycle_of(np_status: object) -> str:
    if not isinstance(np_status, str) or not np_status.strip():
        return "ACTIVE"
    s = np_status.lower()
    if "nagar" in s or "np" in s.split():
        return "CONVERTED_NP"
    if "deduction" in s:
        return "DEDUCTED"
    return "PERMANENTLY_CLOSED"


@dataclass
class Week:
    code: str
    number: int
    start: dt.date
    end: dt.date


@dataclass
class Store:
    dataset_id: int
    file_name: str
    imported_at: dt.datetime | None
    data_as_of: dt.date
    gps: pd.DataFrame  # index gp_code
    daily: pd.DataFrame  # gp_code x date (float, NaN = NA)
    weekly: pd.DataFrame  # gp_code x "W-nn"
    monthly: pd.DataFrame  # gp_code x "YYYY-MM" (all GPs)
    monthly_amc: pd.DataFrame  # gp_code x "YYYY-MM" (AMC period only)
    weeks: list[Week]
    reported: pd.DataFrame
    master_blocks: pd.DataFrame
    # GP-wise AMC conversion plan (index gp_code): category, planned_date, ach_date, current_status, letter_status, letter_date
    amc_plan: pd.DataFrame = field(default_factory=pd.DataFrame)
    # days in `daily` that come from the upload history (earlier files), not from the active file
    history_days: list[dt.date] = field(default_factory=list)
    _week_cache: dict[str, pd.DataFrame] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _memo: OrderedDict[tuple, Any] = field(default_factory=OrderedDict)
    _memo_locks: dict[tuple, threading.Lock] = field(default_factory=dict)

    # ---------------------------------------------------------------- memo
    def memo(self, key: tuple, compute: Callable[[], T]) -> T:
        """Compute once per snapshot; concurrent identical requests wait for the first one instead of
        recomputing. Callers must not mutate the returned value."""
        with self._lock:
            if key in self._memo:
                self._memo.move_to_end(key)
                return self._memo[key]
            key_lock = self._memo_locks.setdefault(key, threading.Lock())
        with key_lock:
            with self._lock:
                if key in self._memo:
                    return self._memo[key]
            value = compute()
            with self._lock:
                self._memo[key] = value
                while len(self._memo) > MEMO_MAX:
                    self._memo.popitem(last=False)
                self._memo_locks.pop(key, None)
            return value

    # ---------------------------------------------------------------- periods
    # `weeks` is in chronological order (start date). Never order by Week.number: numbers wrap W-52 -> W-1.
    def week(self, code: str) -> Week:
        for w in self.weeks:
            if w.code == code:
                return w
        raise KeyError(code)

    def week_index(self, code: str) -> int:
        """Chronological position of a week (use this, not the number, to compare / order weeks)."""
        for i, w in enumerate(self.weeks):
            if w.code == code:
                return i
        raise KeyError(code)

    @property
    def latest_week(self) -> Week:
        return self.weeks[-1]

    def week_containing(self, d: dt.date) -> Week:
        """The file's Fri–Thu week holding `d`; outside the file's weeks the 7-day rhythm continues (numbers 1..52)."""
        for w in self.weeks:
            if w.start <= d <= w.end:
                return w
        anchor = self.weeks[-1] if d > self.weeks[-1].end else self.weeks[0]
        k = (d - anchor.start).days // 7
        n = (anchor.number - 1 + k) % WEEKS_PER_YEAR + 1
        start = anchor.start + dt.timedelta(days=7 * k)
        return Week(f"W-{n}", n, start, start + dt.timedelta(days=6))

    def week_by_number(self, n: int) -> Week:
        """Week "W-n": the file's own week, else the nearest W-n (either side of the file's last week, across the
        year end) on the file's 7-day rhythm."""
        for w in self.weeks:
            if w.number == n:
                return w
        last = self.weeks[-1]
        k = (n - last.number + WEEKS_PER_YEAR // 2) % WEEKS_PER_YEAR - WEEKS_PER_YEAR // 2
        return Week(f"W-{n}", n, last.start + dt.timedelta(days=7 * k), last.end + dt.timedelta(days=7 * k))

    # ---------------------------------------------------------------- availability
    def mtd(self, end: dt.date) -> pd.Series:
        """AMC month-to-date availability as of `end` (inclusive).

        Matches the source formulas: mean of daily values from the later of the
        1st of the month and the GP's AMC date, up to `end`. GPs not under AMC
        by `end` are NaN. `end` is clamped to the last day with data.
        """
        end = min(end, self.data_as_of)
        start = end.replace(day=1)
        dates = [d for d in self.daily.columns if start <= d <= end]
        if not dates or start < self.daily.columns.min():
            return pd.Series(np.nan, index=self.gps.index)
        vals = self.daily[dates].to_numpy(dtype=float)
        amc = self.gps["amc_date"].to_numpy()
        day_arr = np.array(dates, dtype="datetime64[D]")
        amc_arr = np.array([np.datetime64(a, "D") if isinstance(a, dt.date) else np.datetime64("NaT", "D") for a in amc])
        in_amc = day_arr[None, :] >= amc_arr[:, None]  # NaT compares False
        masked = np.where(in_amc, vals, np.nan)
        with np.errstate(all="ignore"):
            counts = np.sum(~np.isnan(masked), axis=1)
            sums = np.nansum(masked, axis=1)
            res = np.where(counts > 0, sums / np.maximum(counts, 1), np.nan)
        is_amc = pd.Series([isinstance(a, dt.date) and a <= end for a in amc], index=self.gps.index)
        return pd.Series(res, index=self.gps.index).where(is_amc)

    def week_frame(self, code: str) -> pd.DataFrame:
        """Per-GP status for a reporting week (cached)."""
        with self._lock:
            if code in self._week_cache:
                return self._week_cache[code]
        w = self.week(code)
        g = self.gps
        end = np.datetime64(w.end, "D")
        hoto = g["hoto_np"] <= end
        amc = g["amc_np"] <= end
        weekly = self.weekly[code] if code in self.weekly.columns else pd.Series(np.nan, index=g.index)
        frame = pd.DataFrame(
            {
                "hoto_done": hoto.to_numpy(),
                "amc": amc.to_numpy(),
                "mtd": self.mtd(w.end).to_numpy(),
                "weekly": weekly.reindex(g.index).where(amc).to_numpy(),
            },
            index=g.index,
        )
        with self._lock:
            self._week_cache[code] = frame
        return frame

    @cached_property
    def one_time_up_sept(self) -> pd.Series:
        """GP had availability > 0 during September (all GPs, monthly column) – the latest September column not after
        the data date (in Jan 2027 that is 2026-09)."""
        limit = f"{self.data_as_of:%Y-%m}"
        cols = [c for c in self.monthly.columns if re.fullmatch(r"\d{4}-09", str(c)) and str(c) <= limit]
        if not cols:
            return pd.Series(False, index=self.gps.index)
        return self.monthly[max(cols)].fillna(0) > 0


_cache: Store | None = None
_cache_lock = threading.Lock()  # guards the variables below; held only for quick reads / swaps, never during a load
_load_lock = threading.Lock()  # single flight: at most one snapshot load at a time
_generation = 0  # bumped on every swap / invalidation so a slower, older load never overwrites a newer state
_checked_at = 0.0  # time.monotonic() of the last active-dataset check
_failed_at = float("-inf")  # time.monotonic() of the last failed load
_last_error: Exception | None = None


def _swap(store: Store | None) -> None:
    global _cache, _generation, _checked_at
    with _cache_lock:
        _cache = store
        _generation += 1
        _checked_at = time.monotonic()


def invalidate_cache() -> None:
    global _failed_at
    _swap(None)
    with _cache_lock:
        _failed_at = float("-inf")


def reload_store() -> None:
    """Build the snapshot of the (new) active dataset and swap it in. Requests keep being served from the
    previous snapshot while it loads. Falls back to a lazy load on the next request if it fails."""
    with _load_lock:
        try:
            fresh = _load()
        except NoDataError:
            invalidate_cache()
            return
        except Exception:
            log.exception("Snapshot reload failed - next request will load it")
            invalidate_cache()
            return
        _swap(fresh)
    warm(fresh)


def warm(store: Store) -> None:
    """Pre-compute what the first dashboard visit asks for (latest week vs previous)."""
    from . import views  # local: views imports this module

    started = time.perf_counter()
    try:
        codes = [w.code for w in store.weeks]
        week, compare = codes[-1], codes[max(0, len(codes) - 2)]
        store.memo(("overview", week, compare), lambda: views.overview(store, week, compare))
        views.meta(store)
    except Exception:  # warming is an optimisation only
        log.exception("Snapshot warm-up failed")
        return
    log.info("Snapshot of dataset %s warmed in %.1fs", store.dataset_id, time.perf_counter() - started)


def get_store() -> Store:
    """The current snapshot. At most every CHECK_EVERY_S a request also checks (one cheap query) whether another
    process – e.g. a CLI import – activated a different dataset; the new snapshot is then built in the background
    while requests keep the current one."""
    global _checked_at
    cached = _cache
    if cached is not None:
        now = time.monotonic()
        with _cache_lock:
            due = now - _checked_at >= CHECK_EVERY_S and now - _failed_at >= RETRY_AFTER_S
            if due:
                _checked_at = now
        if due:
            _check_active(cached)
        return _cache or cached
    return _cold_load()


def _active_dataset_id() -> int | None:
    with SessionLocal() as db:
        row = db.execute(select(Dataset.id, Dataset.data_as_of).where(Dataset.is_active.is_(True)).order_by(Dataset.id.desc()).limit(1)).first()
    return row.id if row is not None and row.data_as_of is not None else None


def _check_active(cached: Store) -> None:
    try:
        active = _active_dataset_id()
    except Exception:
        log.warning("Active dataset check failed", exc_info=True)
        return
    if active == cached.dataset_id or not _load_lock.acquire(blocking=False):
        return  # unchanged, or a load is already running
    log.info("Active dataset changed (%s -> %s) – reloading the snapshot in the background", cached.dataset_id, active)
    try:
        threading.Thread(target=_background_reload, args=(_generation,), name="snapshot-reload", daemon=True).start()
    except Exception:
        _load_lock.release()
        raise


def _background_reload(generation: int) -> None:
    """Runs with _load_lock held (acquired by _check_active)."""
    global _failed_at
    fresh = None
    try:
        fresh = _load()
    except NoDataError:
        with _cache_lock:
            stale = generation != _generation
        if not stale:
            _swap(None)
    except Exception:
        log.exception("Background snapshot reload failed – keeping the current snapshot, retrying later")
        with _cache_lock:
            _failed_at = time.monotonic()
    finally:
        _load_lock.release()
    if fresh is not None:
        with _cache_lock:
            stale = generation != _generation
        if not stale:
            _swap(fresh)
            warm(fresh)


def _cold_load() -> Store:
    """No snapshot yet: load it (single flight – concurrent requests wait for the same load; after a failure they
    get the same error without retrying for RETRY_AFTER_S)."""
    global _failed_at, _last_error
    with _load_lock:
        if _cache is not None:
            return _cache
        if _last_error is not None and time.monotonic() - _failed_at < RETRY_AFTER_S:
            raise _last_error
        try:
            fresh = _load()
        except NoDataError:
            raise
        except Exception as exc:
            with _cache_lock:
                _failed_at, _last_error = time.monotonic(), exc
            raise
        _swap(fresh)
        with _cache_lock:
            _failed_at, _last_error = float("-inf"), None
        return fresh


def _wide(frame: pd.DataFrame, index: pd.Index, as_date: bool = False) -> pd.DataFrame:
    wide = frame.reindex(index)
    if as_date:
        wide.columns = [dt.date.fromisoformat(c) for c in wide.columns]
    return wide.sort_index(axis=1).astype(float)


def _availability(conn, dataset_id: int) -> dict[str, pd.DataFrame]:
    """{kind: gp × period} from the packs; datasets imported before packs existed are read from the long
    table once and packed for the next load."""
    rows = conn.execute(
        select(GpAvailabilityPack.kind, GpAvailabilityPack.gp_codes, GpAvailabilityPack.periods, GpAvailabilityPack.values).where(
            GpAvailabilityPack.dataset_id == dataset_id
        )
    ).all()
    if rows:
        frames = {r.kind: unpack(r.gp_codes, r.periods, r.values) for r in rows}
        return {k: frames.get(k, pd.DataFrame(dtype=float)) for k in KINDS}
    long = conn.execute(text("SELECT gp_code, kind, period, value FROM gp_availability WHERE dataset_id = :d"), {"d": dataset_id}).all()
    frames = wide_frames(long)
    try:
        with engine.begin() as w:
            w.execute(insert(GpAvailabilityPack), [pack(dataset_id, k, f) for k, f in frames.items()])
    except Exception:  # e.g. a parallel load packed it first – the frames are still valid
        log.warning("Could not store availability packs for dataset %s", dataset_id, exc_info=True)
    return frames


def _load() -> Store:
    with SessionLocal() as db:
        ds = db.scalars(select(Dataset).where(Dataset.is_active.is_(True)).order_by(Dataset.id.desc())).first()
        if ds is None or ds.data_as_of is None:
            raise NoDataError("No dataset has been imported yet")
        weeks = [
            Week(w.code, w.number, w.start_date, w.end_date)
            for w in db.scalars(select(DatasetWeek).where(DatasetWeek.dataset_id == ds.id).order_by(DatasetWeek.start_date, DatasetWeek.number))
        ]
        reported = pd.DataFrame(
            [(r.state, r.metric, r.value_num, r.value_text) for r in db.scalars(select(ReportedNumber).where(ReportedNumber.dataset_id == ds.id))],
            columns=["state", "metric", "value_num", "value_text"],
        )
        mblocks = pd.DataFrame(
            [(m.block_code, m.state, m.block_name, m.total_gp_count, m.existing_gps, m.new_gps, m.block_status) for m in db.scalars(select(MasterBlock).where(MasterBlock.dataset_id == ds.id))],
            columns=["block_code", "state", "block_name", "total_gp_count", "existing_gps", "new_gps", "block_status"],
        )
        meta = (ds.id, ds.file_name, ds.finished_at, ds.data_as_of)

    with engine.connect() as conn:
        gps = pd.read_sql(text("SELECT * FROM gps WHERE dataset_id = :d"), conn, params={"d": meta[0]})
        avail = _availability(conn, meta[0])
        amc_plan = pd.read_sql(text("SELECT gp_code, category, planned_date, ach_date, current_status, letter_status, letter_date FROM gp_amc_plan WHERE dataset_id = :d"), conn, params={"d": meta[0]})

    gps = gps.drop(columns=["dataset_id"]).set_index("gp_code").sort_index()
    for c in ("hoto_date", "amc_date", "lms_amc_date", "letter_date"):
        gps[c] = pd.to_datetime(gps[c], errors="coerce").dt.date.where(gps[c].notna(), None)
    gps["hoto_np"] = pd.to_datetime(gps["hoto_date"], errors="coerce").to_numpy(dtype="datetime64[D]")
    gps["amc_np"] = pd.to_datetime(gps["amc_date"], errors="coerce").to_numpy(dtype="datetime64[D]")
    gps["circle_id"] = gps["circle"].map(circle_id)
    gps["district_id"] = gps["circle_id"] + "~" + gps["district"].map(slug)
    gps["block_id"] = gps["circle"].map(circle_code).str.lower() + "-" + gps["block_code"].astype(str)
    gps["lifecycle"] = gps["np_status"].map(lifecycle_of)
    gps["np_status"] = gps["np_status"].where(gps["np_status"].notna(), None)
    gps["revised"] = gps["np_status"].isna()

    idx = gps.index
    daily = _wide(avail["D"], idx, as_date=True)
    # Days the active file no longer carries (e.g. 1–15 Sep in a file whose daily columns start on 16 Sep) are
    # taken from the history of earlier uploads, so "previous month to date" can still be calculated.
    history_days: list[dt.date] = []
    if len(daily.columns):
        with SessionLocal() as db:
            hist = history_frame(db, min(daily.columns))
        if not hist.empty:
            hist = hist.reindex(idx).astype(float)
            history_days = list(hist.columns)
            daily = pd.concat([hist, daily], axis=1).sort_index(axis=1)
    return Store(
        dataset_id=meta[0],
        file_name=meta[1],
        imported_at=meta[2],
        data_as_of=meta[3],
        gps=gps,
        daily=daily,
        history_days=history_days,
        weekly=_wide(avail["W"], idx),
        monthly=_wide(avail["M"], idx),
        monthly_amc=_wide(avail["MA"], idx),
        weeks=weeks,
        reported=reported,
        master_blocks=mblocks,
        amc_plan=_amc_plan(amc_plan, idx),
    )


def _amc_plan(df: pd.DataFrame, index: pd.Index) -> pd.DataFrame:
    """Plan rows of GPs in the GP list, dates as datetime.date (None when blank)."""
    df = df.set_index("gp_code")
    df = df[df.index.isin(index)]
    for c in ("planned_date", "ach_date", "letter_date"):
        df[c] = pd.to_datetime(df[c], errors="coerce").dt.date.where(df[c].notna(), None)
    return df

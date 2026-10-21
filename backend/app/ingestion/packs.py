"""Availability values stored as compressed GP × period matrices (see models.GpAvailabilityPack)."""

from __future__ import annotations

import json
import zlib
from collections.abc import Iterable

import numpy as np
import pandas as pd

KINDS = ("D", "W", "M", "MA")
_DTYPE = np.dtype("<f8")


def wide_frames(rows: Iterable[tuple[str, str, str, float | None]]) -> dict[str, pd.DataFrame]:
    """Long rows (gp_code, kind, period, value) -> {kind: gp_code × period frame}; None becomes NaN."""
    long = pd.DataFrame(list(rows), columns=["gp_code", "kind", "period", "value"])
    long["value"] = pd.to_numeric(long["value"], errors="coerce").astype(float)
    out = {}
    for kind in KINDS:
        part = long[long["kind"] == kind]
        out[kind] = part.pivot(index="gp_code", columns="period", values="value").sort_index().sort_index(axis=1).astype(float)
    return out


def pack(dataset_id: int, kind: str, frame: pd.DataFrame) -> dict:
    values = np.ascontiguousarray(frame.to_numpy(dtype=_DTYPE))
    return {
        "dataset_id": dataset_id,
        "kind": kind,
        "gp_codes": json.dumps([str(g) for g in frame.index]),
        "periods": json.dumps([str(p) for p in frame.columns]),
        "values": zlib.compress(values.tobytes(), 6),
    }


def unpack(gp_codes: str, periods: str, values: bytes) -> pd.DataFrame:
    index, columns = json.loads(gp_codes), json.loads(periods)
    arr = np.frombuffer(zlib.decompress(values), dtype=_DTYPE).reshape(len(index), len(columns))
    return pd.DataFrame(arr.astype(float), index=pd.Index(index, name="gp_code"), columns=pd.Index(columns, name="period"))

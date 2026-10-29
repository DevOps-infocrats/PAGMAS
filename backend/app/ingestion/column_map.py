"""Column and sheet names accepted by the importer.

Built-in names (below) always work. data/column_map.json can ADD more names for any field – e.g. when the
workbook template renames "AMC Date" to "AMC Dt" – without changing code: add the new name, save, upload again.
Names are matched case- and space-insensitively. When several names of one field are present, the name listed
first wins (file names first, then the built-in ones) and a warning is recorded.

The file never removes a built-in name, and a broken file is ignored (with a warning) – an upload never fails
because of it. A name given for two different fields of the same sheet is rejected, so one column can never
feed two fields. The importer never guesses: for a missing required column it only *suggests* similar headers.
"""

from __future__ import annotations

import difflib
import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..config import get_settings
from .workbook import norm

log = logging.getLogger(__name__)
FILE_NAME = "column_map.json"
MAX_BYTES = 64 * 1024

# ---------------------------------------------------------------- built-in names (the current template)

SHEETS: dict[str, tuple[str, ...]] = {
    "gp": ("GP Wise Data",),
    "masterBlock": ("Master Block",),
    "om": ("O&M",),
}

GP_COLUMNS: dict[str, tuple[str, ...]] = {
    "circle": ("Circle",),
    "ba": ("BA",),
    "district": ("District",),
    "block_name": ("Block",),
    "block_code": ("Block Code",),
    "block_hoto_status": ("Block HOTO Status",),
    "gp_name": ("GP",),
    "gp_code": ("GP Code",),
    "location_code": ("Location Code",),
    "np_status": ("Converted to NP & Closed",),
    "gp_type": ("GP Type",),
    "phase": ("Phase",),
    "olt_location": ("OLT Location",),
    "bbnl_km": ("BBNL Live KM",),
    "bsnl_km": ("BSNL Live KM",),
    "total_rkm": ("TOTAL RKM",),
    "lms_amc_date": ("LMS /AMC Date", "LMS / AMC Date", "LMS/AMC Date"),
    "hoto_date": ("HOTO Date",),
    "lot": ("Lot wise",),
    "letter_date": ("Letter Submission Date AMC Incremental",),
    "amc_category": ("AMC / Incremental",),
    "amc_date": ("AMC Date",),
    "am_name": ("AM Name",),
    # GP-wise AMC conversion plan ("Incremental AMC GPs Plan vs Achievement" block of the sheet)
    "plan_category": ("5% Contractual Incremental+ Additional AMC", "5% Contractual Incremental + Additional AMC"),
    "planned_date": ("Planned Date",),
    "ach_date": ("Ach Date", "Achieved Date", "Achievement Date"),
    "plan_status": ("Current Status",),
    "plan_letter_status": ("Letter Status",),
    "plan_letter_date": ("Letter submission Date",),
    "plan_approval_status": ("Approval Status",),  # IE / BSNL approval of the incremental letter
}
GP_REQUIRED: tuple[str, ...] = ("circle", "district", "block_name", "block_code", "gp_name", "gp_code", "total_rkm", "hoto_date", "amc_date")
GP_HEADER_ANCHORS: tuple[str, ...] = ("circle", "gp_code", "total_rkm")  # a row with these three is the header row

MASTER_BLOCK_COLUMNS: dict[str, tuple[str, ...]] = {
    "state": ("State",),
    "block_code": ("Block Code",),
    "block_name": ("Block Name",),
    "total_gp_count": ("Total GP Count",),
    "existing_gps": ("Existing GPs",),
    "new_gps": ("New GPs",),
    "block_status": ("Block Status",),
}
MASTER_BLOCK_REQUIRED: tuple[str, ...] = ("state", "block_code")
MASTER_BLOCK_HEADER_ANCHORS: tuple[str, ...] = ("state", "block_code", "total_gp_count")

# Escalation Matrix (a separate workbook): the header row is the first one with all required columns.
ESCALATION_COLUMNS: dict[str, tuple[str, ...]] = {
    "circle": ("Circle", "State"),
    "ba": ("BA", "Business Area"),
    "district": ("District",),
    "block_name": ("Block", "Block Name"),
    "block_code": ("Block Code",),
    "gp_name": ("GP", "GP Name"),
    "gp_code": ("GP Code",),
    "frt_code": ("FRT Code",),
    "splicer_name": ("Name of splicer", "Splicer Name"),
    "splicer_phone": ("Splicer Contact No.", "Splicer Contact No", "Splicer Contact Number", "Splicer number"),
    "fe_name": ("FE Name",),
    "fe_phone": ("FE Contact No", "FE Contact No.", "FE Contact Number", "FE Number"),
    "am_name": ("AM Name",),
    "am_phone": ("AM Contact No", "AM Contact No.", "AM Contact Number", "AM Number"),
    "am_email": ("AM Email ID", "AM Email", "AM Mail ID"),
    "shq_name": ("SHQ Spoc", "SHQ SPOC", "SME Name"),
    "shq_phone": ("SHQ Spoc Contact No", "SHQ SPOC Contact No", "SHQ Spoc Contact No.", "SME Number"),
    "shq_email": ("SME Email ID", "SME Email", "SHQ Spoc Email ID", "SHQ SPOC Email"),
    "coh_name": ("COH",),
    "coh_phone": ("COH Number", "COH Contact No", "COH No.", "COH No"),
    "coh_email": ("COH Email ID", "COH Email"),
    "cbh_name": ("CBH",),
    "cbh_phone": ("CBH Number", "CBH Contact No", "CBH No.", "CBH No"),
    "cbh_email": ("CBH Email ID", "CBH Email"),
}
ESCALATION_REQUIRED: tuple[str, ...] = ("circle", "gp_code", "frt_code", "fe_name")


# ---------------------------------------------------------------- the file

Names = list[str]


class _File(BaseModel):
    model_config = ConfigDict(extra="forbid")

    help: str | None = Field(None, alias="_help", max_length=4000)
    sheets: dict[str, list[str]] = Field(default_factory=dict)
    gpColumns: dict[str, list[str]] = Field(default_factory=dict)
    masterBlockColumns: dict[str, list[str]] = Field(default_factory=dict)
    escalationColumns: dict[str, list[str]] = Field(default_factory=dict)


@dataclass
class ColumnMap:
    sheets: dict[str, tuple[str, ...]]
    gp: dict[str, tuple[str, ...]]  # field -> normalised names, preferred first
    master_block: dict[str, tuple[str, ...]]
    escalation: dict[str, tuple[str, ...]]
    problems: list[str] = field(default_factory=list)  # file problems, recorded as import warnings


_cache: dict[str, Any] = {"mtime": None, "map": None}
_lock = threading.Lock()


def map_path() -> Path:
    return get_settings().data_dir / FILE_NAME


def _clean(names: list[str], where: str, problems: list[str]) -> list[str]:
    out = []
    for n in names:
        if not isinstance(n, str) or not n.strip() or len(n) > 120:
            problems.append(f"{where}: ignored an empty or too long name")
            continue
        out.append(n)
    return out


def _merge(defaults: dict[str, tuple[str, ...]], extra: dict[str, list[str]], section: str, problems: list[str], check_conflicts: bool) -> dict[str, tuple[str, ...]]:
    unknown = [k for k in extra if k not in defaults]
    for k in unknown:
        problems.append(f"{section}: unknown field '{k}' ignored (known: {', '.join(defaults)})")
    merged: dict[str, list[str]] = {}
    for key, built_in in defaults.items():
        names: list[str] = []
        for n in _clean(extra.get(key, []), f"{section}.{key}", problems) + list(built_in):  # file names first
            if norm(n) not in names:
                names.append(norm(n))
        merged[key] = names
    if check_conflicts:
        owner: dict[str, set[str]] = {}
        for key, names in merged.items():
            for n in names:
                owner.setdefault(n, set()).add(key)
        for n, keys in owner.items():
            if len(keys) > 1:
                built_in_owner = [k for k in keys if n in {norm(x) for x in defaults[k]}]
                for k in keys:
                    if k not in built_in_owner:  # a built-in name always stays with its own field
                        merged[k] = [x for x in merged[k] if x != n]
                problems.append(f"{section}: name '{n}' was given for {', '.join(sorted(keys))} – removed from {', '.join(sorted(set(keys) - set(built_in_owner)))}")
    return {k: tuple(v) for k, v in merged.items()}


def _build(data: _File | None, problems: list[str]) -> ColumnMap:
    extra = data or _File()
    return ColumnMap(
        sheets=_merge(SHEETS, extra.sheets, "sheets", problems, check_conflicts=True),
        gp=_merge(GP_COLUMNS, extra.gpColumns, "gpColumns", problems, check_conflicts=True),
        master_block=_merge(MASTER_BLOCK_COLUMNS, extra.masterBlockColumns, "masterBlockColumns", problems, check_conflicts=True),
        escalation=_merge(ESCALATION_COLUMNS, extra.escalationColumns, "escalationColumns", problems, check_conflicts=True),
        problems=problems,
    )


def load_column_map() -> ColumnMap:
    """Built-in names + data/column_map.json (re-read when the file changes). Never raises."""
    path = map_path()
    try:
        mtime = path.stat().st_mtime if path.exists() else None
    except OSError:
        mtime = None
    with _lock:
        if _cache["map"] is not None and _cache["mtime"] == (str(path), mtime):
            return _cache["map"]
    problems: list[str] = []
    data: _File | None = None
    if mtime is not None:
        try:
            if path.stat().st_size > MAX_BYTES:
                raise ValueError(f"file larger than {MAX_BYTES // 1024} KB")
            data = _File.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, ValidationError) as exc:
            problems.append(f"{FILE_NAME} could not be used ({str(exc).splitlines()[0][:200]}) – built-in column names used")
            log.warning("Column map ignored: %s", exc)
    cmap = _build(data, problems)
    with _lock:
        _cache.update(mtime=(str(path), mtime), map=cmap)
    return cmap


# ---------------------------------------------------------------- matching helpers


@dataclass
class Located:
    columns: dict[str, int]  # field -> column index
    duplicates: dict[str, list[str]]  # field -> headers that all matched (first one used)


def locate(header: list[Any], fields: dict[str, tuple[str, ...]]) -> Located:
    """Column index of every field: the first listed name that appears wins; other matches are reported."""
    normalised = [norm(h) for h in header]
    cols: dict[str, int] = {}
    dups: dict[str, list[str]] = {}
    for key, names in fields.items():
        hits = [(names.index(h), i) for i, h in enumerate(normalised) if h in names]
        if not hits:
            continue
        hits.sort()
        cols[key] = hits[0][1]
        if len(hits) > 1:
            dups[key] = [str(header[i]) for _, i in hits]
    return Located(cols, dups)


def find_header_row(grid: list[list[Any]], fields: dict[str, tuple[str, ...]], anchors: tuple[str, ...], max_rows: int = 15) -> int | None:
    """First row (within max_rows) that contains a name of every anchor field."""
    for i, row in enumerate(grid[:max_rows]):
        cells = {norm(c) for c in row}
        if all(any(n in cells for n in fields[a]) for a in anchors):
            return i
    return None


def resolve_sheet(sheet_names: list[str], key: str, cmap: ColumnMap) -> str | None:
    """Actual sheet name in the workbook for a logical sheet (first listed name that exists)."""
    by_norm = {norm(s): s for s in sheet_names}
    return next((by_norm[n] for n in cmap.sheets[key] if n in by_norm), None)


def suggest(header: list[Any], names: tuple[str, ...], taken: set[int]) -> str | None:
    """Most similar unused header for a missing column (a hint for the admin – never applied automatically)."""
    candidates = {norm(h): str(h) for i, h in enumerate(header) if i not in taken and norm(h)}
    best: tuple[float, str] | None = None
    for n in names:
        for c, original in candidates.items():
            score = difflib.SequenceMatcher(None, n, c).ratio()
            if score >= 0.7 and (best is None or score > best[0]):
                best = (score, original)
    return f'"{best[1]}" ({best[0]:.0%} similar)' if best else None

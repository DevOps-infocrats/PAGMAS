"""Low-level workbook access (xlsb / xlsx / xlsm) via python-calamine."""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any

from python_calamine import CalamineWorkbook

Cell = Any
Grid = list[list[Cell]]

ALLOWED_SUFFIXES = {".xlsb", ".xlsx", ".xlsm"}
# Both xlsx/xlsm and xlsb are ZIP containers -> must start with the ZIP local-file signature.
ZIP_MAGIC = b"PK\x03\x04"


class WorkbookError(Exception):
    """Structural problem that makes the file unusable."""


def check_file_signature(path: Path) -> None:
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise WorkbookError(f"Unsupported file type '{path.suffix}'. Allowed: {', '.join(sorted(ALLOWED_SUFFIXES))}")
    with path.open("rb") as fh:
        if fh.read(4) != ZIP_MAGIC:
            raise WorkbookError("File content is not a valid Excel workbook")


def open_workbook(path: Path) -> CalamineWorkbook:
    check_file_signature(path)
    try:
        return CalamineWorkbook.from_path(str(path))
    except Exception as exc:  # calamine raises various error types
        raise WorkbookError(f"Workbook could not be read: {exc}") from exc


def read_sheet(wb: CalamineWorkbook, name: str) -> Grid:
    if name not in wb.sheet_names:
        raise WorkbookError(f"Required sheet '{name}' not found (found: {', '.join(wb.sheet_names)})")
    return wb.get_sheet_by_name(name).to_python(skip_empty_area=False)


def norm(text: Cell) -> str:
    """Normalise header text: lower-case, single spaces, no surrounding punctuation."""
    if text is None:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip().lower()


def is_blank(v: Cell) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def as_date(v: Cell) -> dt.date | None:
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    return None


def find_row(grid: Grid, required: list[str], max_rows: int = 15) -> int:
    """Index of the first row containing all `required` header labels."""
    want = {norm(r) for r in required}
    for i, row in enumerate(grid[:max_rows]):
        if want <= {norm(c) for c in row}:
            return i
    raise WorkbookError(f"Header row with columns {required} not found")

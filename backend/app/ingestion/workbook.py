"""Low-level workbook access (xlsb / xlsx) via python-calamine, and the file checks every data upload passes first."""

from __future__ import annotations

import datetime as dt
import re
import zipfile
from pathlib import Path
from typing import Any

from python_calamine import CalamineWorkbook

Cell = Any
Grid = list[list[Cell]]

# Macro workbooks (.xlsm) are refused: the data files never need macros and a macro file is a needless risk.
ALLOWED_SUFFIXES = {".xlsb", ".xlsx"}
# Both xlsx and xlsb are ZIP containers -> must start with the ZIP local-file signature.
ZIP_MAGIC = b"PK\x03\x04"
# The part every genuine workbook package has (a renamed ZIP / document does not)
WORKBOOK_PART = {".xlsx": "xl/workbook.xml", ".xlsb": "xl/workbook.bin"}


class WorkbookError(Exception):
    """Structural problem that makes the file unusable."""


def check_file_signature(path: Path) -> None:
    """Layered file checks, cheapest first (fail fast): type -> empty -> ZIP signature -> genuine workbook package ->
    zip-bomb guard. Only then is the file handed to the workbook reader."""
    suffix = path.suffix.lower()
    if suffix == ".xlsm":
        raise WorkbookError("Macro workbooks (.xlsm) are not accepted – save the file as .xlsx or .xlsb (Excel: File → Save As) and upload again")
    if suffix not in ALLOWED_SUFFIXES:
        raise WorkbookError(f"Unsupported file type '{path.suffix}'. Allowed: {', '.join(sorted(ALLOWED_SUFFIXES))}")
    size = path.stat().st_size
    if size == 0:
        raise WorkbookError("The file is empty (0 bytes) – please choose the workbook again")
    with path.open("rb") as fh:
        if fh.read(4) != ZIP_MAGIC:
            raise WorkbookError("File content is not a valid Excel workbook (it may be a renamed file of another type)")
    check_package(path, size)


def check_package(path: Path, size: int | None = None) -> None:
    """The ZIP must be a real workbook package of its type and must not expand absurdly (zip bomb): limits come from
    ZIP_MAX_UNCOMPRESSED_MB / ZIP_MAX_RATIO (the real master file is ~7 MB -> ~60 MB, ~9x)."""
    from ..config import get_settings

    s = get_settings()
    size = size if size is not None else path.stat().st_size
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            names = {i.filename for i in infos}
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        raise WorkbookError(f"The file is damaged and cannot be opened as an Excel workbook ({type(exc).__name__})") from None
    part = WORKBOOK_PART.get(path.suffix.lower())
    if "[Content_Types].xml" not in names or (part and part not in names):
        other = next((k for k, v in WORKBOOK_PART.items() if v in names and k != path.suffix.lower()), None)
        hint = f" – it looks like a {other} file with the wrong extension" if other else ""
        raise WorkbookError(f"The file is not a genuine {path.suffix.lower()} workbook{hint}")
    expanded = sum(i.file_size for i in infos)
    if expanded > s.zip_max_uncompressed_mb * 1024 * 1024 or expanded > max(size, 1) * s.zip_max_ratio:
        raise WorkbookError(
            f"The file expands to {expanded / 1024 / 1024:,.0f} MB when opened ({expanded / max(size, 1):,.0f}x its size) – refused as unsafe "
            f"(limits {s.zip_max_uncompressed_mb} MB, {s.zip_max_ratio}x)"
        )


def open_workbook(path: Path) -> CalamineWorkbook:
    check_file_signature(path)
    try:
        return CalamineWorkbook.from_path(str(path))
    except Exception as exc:  # calamine raises various error types
        raise WorkbookError(f"Workbook could not be read: {exc}") from exc


def read_sheet(wb: CalamineWorkbook, name: str, nrows: int | None = None) -> Grid:
    if name not in wb.sheet_names:
        raise WorkbookError(f"Required sheet '{name}' not found (found: {', '.join(wb.sheet_names)})")
    try:
        return wb.get_sheet_by_name(name).to_python(skip_empty_area=False, nrows=nrows)
    except Exception as exc:  # corrupt sheet data
        raise WorkbookError(f"Sheet '{name}' could not be read: {exc}") from exc


def norm(text: Cell) -> str:
    """Normalise header text: lower-case, single spaces, no surrounding punctuation."""
    if text is None:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip().lower()


def is_blank(v: Cell) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


EXCEL_EPOCH = dt.date(1899, 12, 30)
_DMY_RE = re.compile(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4}|\d{2})$")
_ISO_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")


def as_date(v: Cell) -> dt.date | None:
    """Date cells, Excel serial numbers (20000..80000) and day-first text ('15-10-2026', '15.10.26'); else None."""
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return EXCEL_EPOCH + dt.timedelta(days=int(v)) if 20000 <= v <= 80000 else None
    if isinstance(v, str):
        s = v.strip()
        if m := _DMY_RE.match(s):
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            y = y + 2000 if y < 100 else y
        elif m := _ISO_RE.match(s):
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            return None
        try:
            return dt.date(y, mo, d)
        except ValueError:
            return None
    return None


def clean_code(v: Cell) -> str | None:
    """GP / block code as text: 262368.0 -> '262368', ' 262368.0 ' -> '262368', 'O033977' (letter O) -> '0033977'."""
    if is_blank(v) or (isinstance(v, float) and v != v):
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return str(int(v)) if float(v).is_integer() else str(v)
    s = re.sub(r"\s+", " ", str(v)).strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    if re.fullmatch(r"[Oo]\d+", s):
        s = "0" + s[1:]
    return s or None


def code_key(code: str) -> str:
    """Comparison key of a cleaned code: digit-only codes without leading zeros ('033977' == '33977')."""
    return (code.lstrip("0") or "0") if code.isdigit() else code.upper()


def find_row(grid: Grid, required: list[str], max_rows: int = 15) -> int:
    """Index of the first row containing all `required` header labels."""
    want = {norm(r) for r in required}
    for i, row in enumerate(grid[:max_rows]):
        if want <= {norm(c) for c in row}:
            return i
    raise WorkbookError(f"Header row with columns {required} not found")

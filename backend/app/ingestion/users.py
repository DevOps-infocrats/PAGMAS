"""Bulk user import: read names and e-mail addresses from an Excel (xlsx / xlsb) or CSV file.

Only reads the file. The admin API decides which rows become accounts (new e-mail addresses only)."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path

from python_calamine import CalamineWorkbook

from ..mail.smtp import valid_address
from .workbook import ALLOWED_SUFFIXES, WorkbookError, check_file_signature, is_blank, norm

USER_IMPORT_SUFFIXES = ALLOWED_SUFFIXES | {".csv"}
MAX_ROWS = 1000
HEADER_SCAN_ROWS = 15
NAME_HEADERS = {"name", "full name", "user name", "username", "employee name", "emp name", "person name", "staff name", "user"}
EMAIL_HEADERS = {"email", "e-mail", "email id", "e-mail id", "emailid", "email address", "e-mail address", "mail", "mail id", "official email", "official email id"}


@dataclass
class ImportRow:
    row: int  # row number in the sheet (1-based, as Excel shows it)
    name: str
    email: str  # normalised lower-case address, or the raw text when invalid
    problem: str | None = None


def _header(cell: object) -> str:
    return norm(cell).replace("_", " ").strip(" :.*")


def _grid(path: Path) -> list[list[object]]:
    if path.suffix.lower() == ".csv":
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1252", errors="replace")
        return [list(r) for r in csv.reader(io.StringIO(text))]
    check_file_signature(path)
    try:
        wb = CalamineWorkbook.from_path(str(path))
    except Exception as exc:  # calamine raises various error types
        raise WorkbookError(f"Workbook could not be read: {exc}") from exc
    # first sheet that has a Name and an E-mail header, else the first sheet
    first: list[list[object]] | None = None
    for name in wb.sheet_names:
        try:
            grid = wb.get_sheet_by_name(name).to_python(skip_empty_area=False)
        except Exception as exc:
            raise WorkbookError(f"Sheet '{name}' could not be read: {exc}") from exc
        if first is None:
            first = grid
        if _find_columns(grid):
            return grid
    return first or []


def _find_columns(grid: list[list[object]]) -> tuple[int, int, int] | None:
    """(header row index, name column, email column) of the first row that names both columns."""
    for i, row in enumerate(grid[:HEADER_SCAN_ROWS]):
        heads = [_header(c) for c in row]
        email = next((j for j, h in enumerate(heads) if h in EMAIL_HEADERS), None)
        if email is None:
            email = next((j for j, h in enumerate(heads) if "mail" in h), None)
        name = next((j for j, h in enumerate(heads) if h in NAME_HEADERS and j != email), None)
        if name is None:
            name = next((j for j, h in enumerate(heads) if "name" in h and "mail" not in h and j != email), None)
        if email is not None and name is not None:
            return i, name, email
    return None


def read_users(path: Path) -> list[ImportRow]:
    """Every non-empty data row with its problem (None = can be imported). Raises WorkbookError if the file has no
    Name / E-mail header or too many rows."""
    if path.suffix.lower() not in USER_IMPORT_SUFFIXES:
        raise WorkbookError(f"Unsupported file type '{path.suffix}'. Allowed: {', '.join(sorted(USER_IMPORT_SUFFIXES))}")
    grid = _grid(path)
    found = _find_columns(grid)
    if not found:
        raise WorkbookError("No header row with a 'Name' and an 'Email' column found in the first rows of the file.")
    head, nc, ec = found
    out: list[ImportRow] = []
    seen: set[str] = set()
    for i, row in enumerate(grid[head + 1 :], start=head + 2):
        name_cell = row[nc] if nc < len(row) else None
        email_cell = row[ec] if ec < len(row) else None
        if is_blank(name_cell) and is_blank(email_cell):
            continue
        name = " ".join(str(name_cell or "").split())
        raw = str(email_cell or "").strip()
        email = valid_address(raw)
        r = ImportRow(row=i, name=name, email=email or raw)
        if not raw:
            r.problem = "E-mail missing"
        elif not email:
            r.problem = "Invalid e-mail address"
        elif len(name) < 2:
            r.problem = "Name missing"
        elif len(name) > 120:
            r.problem = "Name longer than 120 characters"
        elif email in seen:
            r.problem = "Duplicate e-mail in the file"
        if email:
            seen.add(email)
        out.append(r)
        if len(out) > MAX_ROWS:
            raise WorkbookError(f"The file has more than {MAX_ROWS} users – split it into smaller files.")
    return out

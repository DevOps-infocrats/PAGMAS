"""Bulk user import: read names and e-mail addresses – and optionally the areas each user may see (Circle, BA,
District, Block, GP columns) – from an Excel (xlsx / xlsb) or CSV file.

Only reads the file (resolve_areas checks the areas against the active data). The admin API decides which rows become
accounts (new e-mail addresses only)."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from python_calamine import CalamineWorkbook

from ..mail.smtp import valid_address
from ..security.core import password_problems
from .workbook import ALLOWED_SUFFIXES, WorkbookError, check_file_signature, is_blank, norm

USER_IMPORT_SUFFIXES = ALLOWED_SUFFIXES | {".csv"}
MAX_ROWS = 1000
HEADER_SCAN_ROWS = 15
NAME_HEADERS = {"name", "full name", "user name", "username", "employee name", "emp name", "person name", "staff name", "user"}
EMAIL_HEADERS = {"email", "e-mail", "email id", "e-mail id", "emailid", "email address", "e-mail address", "mail", "mail id", "official email", "official email id"}
# optional area columns (most general first): each cell may hold several values separated by , ; | or new lines
AREA_HEADERS: dict[str, set[str]] = {
    "circle": {"circle", "circle name", "state", "state name"},
    "ba": {"ba", "ba name", "business area", "business area name"},
    "district": {"district", "district name"},
    "block": {"block", "block name", "block code", "block name / code", "block name/code"},
    "gp": {"gp", "gp code", "gp name", "gp name / code", "gp name/code", "gram panchayat", "lgd code", "gp lgd code"},
}
AREA_ORDER = ("circle", "ba", "district", "block", "gp")
# optional: the user's own initial password (empty cell = the temporary USER_IMPORT_PASSWORD)
PASSWORD_HEADERS = {"password", "initial password", "temporary password", "login password", "pwd", "pass"}
# FRT team login: the Escalation Matrix FRT code. A row with an FRT code and NO e-mail creates an account that signs in
# with the FRT code (app.security.frt_login); with an e-mail, the code is set on that account.
FRT_HEADERS = {"frt code", "frt", "frt id", "frt team", "frt team code", "frt login"}
EXAMPLE_FRT_PREFIX = "EXAMPLE"
_AREA_NAMES = set().union(*AREA_HEADERS.values())


@dataclass
class ImportRow:
    row: int  # row number in the sheet (1-based, as Excel shows it)
    name: str
    email: str  # normalised lower-case address, or the raw text when invalid
    problem: str | None = None
    areas: dict[str, list[str]] = field(default_factory=dict)  # level -> values typed in the file (empty = none)
    password: str | None = field(default=None, repr=False)  # from the Password column; None = the temporary password
    frt_code: str | None = None  # FRT Code column (normalised); checked against the Escalation Matrix by the import
    frt_only: bool = False  # no e-mail: the account signs in with the FRT code


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


def _find_columns(grid: list[list[object]]) -> tuple[int, int, int | None] | None:
    """(header row index, name column, email column or None) of the first row that names the Name column and an E-mail
    and / or FRT Code column."""
    for i, row in enumerate(grid[:HEADER_SCAN_ROWS]):
        heads = [_header(c) for c in row]
        email = next((j for j, h in enumerate(heads) if h in EMAIL_HEADERS), None)
        if email is None:
            email = next((j for j, h in enumerate(heads) if "mail" in h), None)
        frt = next((j for j, h in enumerate(heads) if h in FRT_HEADERS and j != email), None)
        name = next((j for j, h in enumerate(heads) if h in NAME_HEADERS and j != email), None)
        if name is None:
            name = next((j for j, h in enumerate(heads) if "name" in h and "mail" not in h and h not in _AREA_NAMES and j != email and j != frt), None)
        if name is not None and (email is not None or frt is not None):
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
        raise WorkbookError("No header row with a 'Name' and an 'Email' (or 'FRT Code') column found in the first rows of the file.")
    head, nc, ec = found
    heads = [_header(c) for c in grid[head]]
    area_cols = {lvl: j for lvl in AREA_ORDER for j in [next((j for j, h in enumerate(heads) if h in AREA_HEADERS[lvl] and j not in (nc, ec)), None)] if j is not None}
    pc = next((j for j, h in enumerate(heads) if h in PASSWORD_HEADERS and j not in (nc, ec)), None)
    fc = next((j for j, h in enumerate(heads) if h in FRT_HEADERS and j not in (nc, ec)), None)
    from ..security.frt_login import frt_code_norm, frt_login_email
    out: list[ImportRow] = []
    seen: set[str] = set()
    for i, row in enumerate(grid[head + 1 :], start=head + 2):
        name_cell = row[nc] if nc < len(row) else None
        email_cell = row[ec] if ec is not None and ec < len(row) else None
        frt_cell = row[fc] if fc is not None and fc < len(row) else None
        if is_blank(name_cell) and is_blank(email_cell) and is_blank(frt_cell):
            continue
        name = " ".join(str(name_cell or "").split())
        raw = str(email_cell or "").strip()
        code = frt_code_norm(str(frt_cell)) if not is_blank(frt_cell) else None
        frt_only = not raw and code is not None
        email = frt_login_email(code) if frt_only else valid_address(raw)
        r = ImportRow(row=i, name=name, email=email or raw, areas={lvl: _values(row[j] if j < len(row) else None) for lvl, j in area_cols.items()}, frt_code=code, frt_only=frt_only)
        pw_cell = row[pc] if pc is not None and pc < len(row) else None
        if not is_blank(pw_cell):
            if isinstance(pw_cell, float) and pw_cell.is_integer():
                pw_cell = int(pw_cell)  # a number-only password typed in Excel
            r.password = str(pw_cell).strip()
        pw_problems = password_problems(r.password, email or "") if r.password is not None else []
        if not raw and code is None:
            r.problem = "E-mail (or FRT code) missing"
        elif code is not None and code.startswith(EXAMPLE_FRT_PREFIX):
            r.problem = "Example row of the template – replace it with a real user"
        elif not email:
            r.problem = "Invalid e-mail address"
        elif len(name) < 2:
            r.problem = "Name missing"
        elif len(name) > 120:
            r.problem = "Name longer than 120 characters"
        elif email.endswith("@" + EXAMPLE_DOMAIN):
            r.problem = "Example row of the template – replace it with a real user"
        elif email in seen:
            r.problem = "Duplicate FRT code in the file" if frt_only else "Duplicate e-mail in the file"
        elif pw_problems:
            r.problem = "Password needs " + "; ".join(pw_problems)
        if email:
            seen.add(email)
        out.append(r)
        if len(out) > MAX_ROWS:
            raise WorkbookError(f"The file has more than {MAX_ROWS} users – split it into smaller files.")
    return out


def has_password_column(rows: list[ImportRow]) -> bool:
    return any(r.password is not None for r in rows)


def has_area_columns(rows: list[ImportRow]) -> bool:
    return any(r.areas for r in rows)


def _values(cell: object) -> list[str]:
    if is_blank(cell):
        return []
    if isinstance(cell, float) and cell.is_integer():
        cell = int(cell)  # a GP / block code typed as a number
    return list(dict.fromkeys(v for v in (" ".join(p.split()) for p in re.split(r"[,;|\n]+", str(cell))) if v))


def _key(v: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(v).lower())


LEVEL_TITLE = {"circle": "Circle", "ba": "BA", "district": "District", "block": "Block", "gp": "GP"}


class AreaResolver:
    """Turns the area columns of import rows into User Management areas (level, id), checked against the active data
    (the place names are normalised once per import)."""

    def __init__(self, g: pd.DataFrame | None):
        self.g = g
        if g is None:
            return
        from ..analytics.store import ba_ids

        code = pd.Series(g.index.astype(str), index=g.index)
        raw = {
            "circle": (g["circle_id"], [g["circle"]]),
            "ba": (ba_ids(g), [g["ba"]] if "ba" in g.columns else []),
            "district": (g["district_id"], [g["district"]]),
            "block": (g["block_id"], [g["block_name"], g["block_code"]]),
            "gp": (code, [code, g["name"]]),
        }
        self.keys = {lvl: (ids, pd.concat([t.map(_key) for t in texts], axis=1) if texts else None) for lvl, (ids, texts) in raw.items()}

    def resolve(self, areas: dict[str, list[str]]) -> tuple[list[tuple[str, str]], str | None]:
        """The areas of one row, or a problem. Only the most specific filled column is stored (e.g. Circle + BA = those
        BAs); the columns above it only pick the right one among same-named places (a block name found in two circles
        needs the Circle, or use the block code). Every value must match exactly one place of the active data – a row
        whose area is not found is skipped, never created with wider access. No area = ([], None)."""
        filled = [lvl for lvl in AREA_ORDER if areas.get(lvl)]
        if not filled:
            return [], None
        g = self.g
        if g is None:
            return [], "No active data – the areas cannot be checked"
        inside = pd.Series(True, index=g.index)  # GPs of the columns above (narrowed level by level)
        for n, lvl in enumerate(filled):
            ids, texts = self.keys[lvl]
            above = "/".join(LEVEL_TITLE[x] for x in filled[:n])
            hits = pd.Series(False, index=g.index)
            chosen: list[str] = []
            for v in areas[lvl]:
                k = _key(v)
                found = sorted(set(ids[inside & ids.notna() & (texts == k).any(axis=1)])) if texts is not None and k else []
                if not found:
                    return [], f"{LEVEL_TITLE[lvl]} '{v}' not found" + (f" in the given {above}" if above else "")
                if len(found) > 1:
                    return [], (
                        f"GP '{v}' matches several GPs – use the GP code"
                        if lvl == "gp"
                        else f"{LEVEL_TITLE[lvl]} '{v}' is in more than one place – fill the column above it (Circle / BA / District)" + (" or use the block code" if lvl == "block" else "")
                    )
                chosen.append(found[0])
                hits |= ids == found[0]
            if n == len(filled) - 1:
                return [(lvl, i) for i in dict.fromkeys(chosen)], None
            inside &= hits
        return [], None


# ---------------------------------------------------------------- template (User Management → Import users)

TEMPLATE_FILE = "user-import-template.xlsx"
TEMPLATE_COLUMNS = ("Name", "Email", "Password", "Circle", "BA", "District", "Block", "GP", "FRT Code")  # read by the headers above
EXAMPLE_DOMAIN = "example.com"  # rows of the template: never imported (replace them with real users)


def _template_examples(g: pd.DataFrame | None) -> list[list[object]]:
    """Example rows with places of the active data (so the names are spelt as the import expects), else generic ones."""
    circle, ba, block = "Rajasthan", "Jaipur", "Sanganer"
    if g is not None and not g.empty and "ba" in g.columns:
        sub = g[g["ba"].map(lambda v: isinstance(v, str) and bool(v.strip()))]
        if not sub.empty:
            first = sub.iloc[0]
            circle, ba, block = str(first["circle"]).title(), " ".join(str(first["ba"]).split()).title(), str(first["block_name"]).title()
    return [
        ["Ravi Kumar", f"ravi.kumar@{EXAMPLE_DOMAIN}", "Ravi@Pratap2026", circle, ba, None, None, None, None],
        ["Sita Devi", f"sita.devi@{EXAMPLE_DOMAIN}", None, circle, ba, None, block, None, None],
        ["Neha Sharma", f"neha.sharma@{EXAMPLE_DOMAIN}", "Neha#Bsnl12345", circle, None, None, None, None, None],
        ["FRT Team Kota", None, "Frt@Pratap2026", None, None, None, None, None, f"{EXAMPLE_FRT_PREFIX}-FRT-1"],
    ]


def _ba_list(g: pd.DataFrame | None) -> str:
    """Every circle's BAs of the active data, e.g. "Rajasthan: Ajmer, Alwar; Haryana: …" (never a fixed list)."""
    if g is None or g.empty or "ba" not in g.columns:
        return ""
    tidy = lambda v: " ".join(str(v).split()).title() if isinstance(v, str) and v.strip() and v.strip() != "0" else None  # noqa: E731
    out = []
    for circle, cg in g.groupby("circle", sort=True):
        bas = sorted({b for b in cg["ba"].map(tidy) if b})
        if bas:
            out.append(f"{str(circle).title()}: {', '.join(bas)}")
    return "; ".join(out)


def _first_ba(g: pd.DataFrame | None) -> str:
    row = _template_examples(g)[0]
    return str(row[4] or "Jaipur")


def build_template(g: pd.DataFrame | None, temporary_password: str) -> bytes:
    """The import file to fill in: a Users sheet (the columns the import reads, three example rows) and an
    Instructions sheet (what each column means and how to write the values)."""
    import xlsxwriter

    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    need = wb.add_format({"bold": True, "bg_color": "#0F766E", "font_color": "#FFFFFF", "border": 1})
    opt = wb.add_format({"bold": True, "bg_color": "#E8F1FB", "border": 1})
    eg = wb.add_format({"italic": True, "font_color": "#6B7280"})
    ws = wb.add_worksheet("Users")
    widths = (22, 32, 20, 16, 18, 18, 20, 16, 18)
    for c, (title, w) in enumerate(zip(TEMPLATE_COLUMNS, widths)):
        ws.write(0, c, title, need if title in ("Name", "Email") else opt)
        ws.set_column(c, c, w)
    for r, row in enumerate(_template_examples(g), start=1):
        for c, v in enumerate(row):
            if v is not None:
                ws.write_string(r, c, str(v), eg)
    ws.freeze_panes(1, 0)
    ws.write_comment(0, 2, "Optional. At least 12 characters with 3 of: lower-case, upper-case, digits, symbols. Empty = the temporary password.")
    ws.write_comment(0, 8, "FRT team login: the FRT code exactly as in the Escalation Matrix. With no e-mail, the user signs in with this FRT code and the password.")

    info = wb.add_worksheet("Instructions")
    bold = wb.add_format({"bold": True})
    wrap = wb.add_format({"text_wrap": True, "valign": "top"})
    info.set_column(0, 0, 20)
    info.set_column(1, 1, 100)
    rows = [
        ("Column", "What to fill"),
        ("Name", "Required. The user's full name."),
        ("Email", "The e-mail the user signs in with (required unless an FRT Code is given). An address that is already a dashboard user is not changed."),
        ("FRT Code", "Optional – FRT team login. The FRT code exactly as in the Escalation Matrix (FRT Code column). With an e-mail: that user reports the GPs of this FRT code. Without an e-mail: the user signs in with the FRT code and the password (one such login per FRT code). A code that is not in the Escalation Matrix skips the row."),
        ("Password", f"Optional. The user's own password: at least 12 characters with 3 of lower-case, upper-case, digits, symbols, and not containing the e-mail name. Empty = the temporary password {temporary_password}. A weak password skips the row."),
        ("Circle", "Optional. State / circle name, e.g. Rajasthan."),
        ("BA", "Optional. Business area name, e.g. Jaipur."),
        ("District", "Optional. District name."),
        ("Block", "Optional. Block name or block code."),
        ("GP", "Optional. GP code (or GP name)."),
        ("", ""),
        ("Areas", "Circle / BA / District / Block / GP decide what the user sees on the dashboard and in the AMC Conversion e-mail. The most specific filled column counts: Circle Rajasthan + BA Jaipur = only Jaipur BA; + Block = only that block. The columns above only find the right place when names repeat (a block name in two circles needs the Circle, or use the block code)."),
        ("Several", "Several values in one cell are separated by commas, e.g. Jaipur, Ajmer."),
        ("No area", "All area columns empty = the user sees every circle."),
        ("Not found", "A name that is not in the current data skips the row (the preview shows why) – nobody gets wider access by mistake."),
        ("Examples", f"The grey rows with @{EXAMPLE_DOMAIN} addresses are examples and are never imported – replace them with your users."),
    ]
    tip = wb.add_format({"bold": True, "bg_color": "#E8F1FB", "border": 1})
    ok = wb.add_format({"text_wrap": True, "valign": "top", "font_color": "#15803D", "bold": True})
    for r, (a, b) in enumerate(rows):
        info.write(r, 0, a, bold)
        info.write(r, 1, b, bold if r == 0 else wrap)
    # how to write each value so that every row is accepted (shown as "write it like this")
    r0 = len(rows) + 1
    info.set_column(2, 2, 40)
    info.write_row(r0, 0, ["How to fill", "Instruction", "Write it like this"], tip)
    howto = [
        ("Several places", "Two or more BAs / districts / blocks in one cell: separate them with a comma (not with / or 'and').", "Barmer, Jaisalmer"),
        ("BA name", "Write the BA exactly as it is called in the dashboard." + (f" BAs in the current data – {_ba_list(g)}." if _ba_list(g) else ""), _first_ba(g)),
        ("Circle and BA", "Write the state in the Circle column and a business area of that state in the BA column – or leave BA empty.", "Circle: Assam   BA: Kamrup"),
        ("District", "When a District is filled, leave BA empty – the district alone decides the area, so the BA is not needed.", "Circle: Rajasthan   District: Sikar"),
        ("E-mail", "One complete e-mail per row, without spaces.", "fe.kota@telecrats.com"),
        ("One row per user", "Each e-mail only once in the file. A user with several areas: put them in one cell with commas.", "District: Bundi, Baran"),
        ("Every row", "Fill Name and Email in every row – a row without an e-mail cannot become a user (except an FRT login with its FRT code).", "Ravi Kumar | ravi@pratap.co.in"),
        ("FRT login", "No e-mail? Write the FRT code in FRT Code and a password – the FRT signs in with the code.", "FRT Team Kota | (empty) | Frt@Pratap2026 | … | RJKOTA-001"),
        ("Password", "At least 12 characters with 3 of: small letters, capital letters, numbers, symbols; do not use the e-mail name.", "Ravi@Pratap2026"),
        ("Existing users", "The import only creates new users. To change the areas or password of an existing user, use Edit on User Management.", "Edit → Areas"),
        ("Example rows", f"Delete the grey example rows (@{EXAMPLE_DOMAIN}) and write your own users.", "Your users only"),
    ]
    for i, (a, b, w) in enumerate(howto, start=r0 + 1):
        info.write(i, 0, a, bold)
        info.write(i, 1, b, wrap)
        info.write(i, 2, w, ok)
    wb.close()
    return buf.getvalue()

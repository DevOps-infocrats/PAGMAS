"""Builds docs/Pratap_Network_Analytics_Project_Report.pdf (project documentation)."""

import sys
from pathlib import Path

from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    CondPageBreak,
    Image,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Preformatted,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(sys.argv[1])
OUT = ROOT / "docs" / "Pratap_Network_Analytics_Project_Report.pdf"
LOGO = ROOT / "frontend" / "public" / "brand" / "pratap-logo.png"
WORDMARK = ROOT / "frontend" / "public" / "brand" / "pratap-wordmark.png"

pdfmetrics.registerFont(TTFont("Body", "C:/Windows/Fonts/calibri.ttf"))
pdfmetrics.registerFont(TTFont("Body-Bold", "C:/Windows/Fonts/calibrib.ttf"))
pdfmetrics.registerFont(TTFont("Body-Italic", "C:/Windows/Fonts/calibrii.ttf"))
pdfmetrics.registerFont(TTFont("Mono", "C:/Windows/Fonts/consola.ttf"))
from reportlab.pdfbase.pdfmetrics import registerFontFamily  # noqa: E402

registerFontFamily("Body", normal="Body", bold="Body-Bold", italic="Body-Italic", boldItalic="Body-Bold")

INK = colors.HexColor("#0E1726")
MUTED = colors.HexColor("#5B6675")
BRAND = colors.HexColor("#0877A6")
GREEN = colors.HexColor("#19BD4A")
BLUE = colors.HexColor("#0A8FC4")
GRID = colors.HexColor("#E4E7EC")
SOFT = colors.HexColor("#F3F6F9")
GOOD = colors.HexColor("#0B6E2C")
GOOD_BG = colors.HexColor("#E8F6EC")
WARN = colors.HexColor("#8A5300")
WARN_BG = colors.HexColor("#FDF4E1")

S = {
    "h1": ParagraphStyle("h1", fontName="Body-Bold", fontSize=20, leading=25, textColor=INK, spaceBefore=4, spaceAfter=8),
    "h2": ParagraphStyle("h2", fontName="Body-Bold", fontSize=13.5, leading=18, textColor=BRAND, spaceBefore=12, spaceAfter=5),
    "h3": ParagraphStyle("h3", fontName="Body-Bold", fontSize=11.5, leading=15, textColor=INK, spaceBefore=8, spaceAfter=3),
    "body": ParagraphStyle("body", fontName="Body", fontSize=10.5, leading=15, textColor=INK, spaceAfter=5, alignment=TA_LEFT),
    "small": ParagraphStyle("small", fontName="Body", fontSize=9, leading=12.5, textColor=MUTED, spaceAfter=4),
    "cell": ParagraphStyle("cell", fontName="Body", fontSize=9.2, leading=12, textColor=INK),
    "cellb": ParagraphStyle("cellb", fontName="Body-Bold", fontSize=9.2, leading=12, textColor=INK),
    "head": ParagraphStyle("head", fontName="Body-Bold", fontSize=9, leading=11.5, textColor=MUTED),
    "mono": ParagraphStyle("mono", fontName="Mono", fontSize=8.6, leading=12, textColor=INK, backColor=SOFT, borderPadding=(6, 6, 6, 6), spaceBefore=4, spaceAfter=10),
    "callout": ParagraphStyle("callout", fontName="Body", fontSize=10, leading=14, textColor=INK),
}

story: list = []
P = lambda t, s="body": Paragraph(t, S[s])  # noqa: E731
H1 = lambda t: P(t, "h1")  # noqa: E731
H2 = lambda t: P(t, "h2")  # noqa: E731
H3 = lambda t: P(t, "h3")  # noqa: E731


def bullets(items, style="body"):
    return ListFlowable(
        [ListItem(P(i, style), leftIndent=12, value="•") for i in items],
        bulletType="bullet",
        start="•",
        leftIndent=12,
        bulletFontName="Body",
        bulletColor=BRAND,
        spaceAfter=4,
    )


def table(rows, widths, header=True, zebra=True, bold_first_col=False):
    data = []
    for r_i, row in enumerate(rows):
        cells = []
        for c_i, c in enumerate(row):
            if isinstance(c, str):
                style = "head" if header and r_i == 0 else ("cellb" if bold_first_col and c_i == 0 else "cell")
                cells.append(Paragraph(c, S[style]))
            else:
                cells.append(c)
        data.append(cells)
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    st = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, GRID),
    ]
    if header:
        st += [("BACKGROUND", (0, 0), (-1, 0), SOFT), ("LINEBELOW", (0, 0), (-1, 0), 0.8, GRID)]
    t.setStyle(TableStyle(st))
    return t


def callout(text, tone="info"):
    bg, edge = {"info": (colors.HexColor("#E6F3F9"), BRAND), "good": (GOOD_BG, GOOD), "warn": (WARN_BG, WARN)}[tone]
    t = Table([[Paragraph(text, S["callout"])]], colWidths=[174 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg), ("LINEBEFORE", (0, 0), (0, -1), 3, edge), ("LEFTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    return KeepTogether([t, Spacer(1, 8)])


def stat_tiles(items):
    cells = []
    for value, label in items:
        cells.append(Paragraph(f'<font name="Body-Bold" size="17" color="#0E1726">{value}</font><br/><font size="8.5" color="#5B6675">{label}</font>', S["cell"]))
    t = Table([cells], colWidths=[174 * mm / len(items)] * len(items))
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, GRID), ("INNERGRID", (0, 0), (-1, -1), 0.6, GRID), ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8), ("LEFTPADDING", (0, 0), (-1, -1), 9)]))
    return KeepTogether([t, Spacer(1, 10)])


def architecture():
    d = Drawing(174 * mm, 76 * mm)
    W = 174 * mm

    def box(x, y, w, h, title, sub, fill=colors.white, edge=BRAND):
        d.add(Rect(x, y, w, h, rx=5, ry=5, fillColor=fill, strokeColor=edge, strokeWidth=1))
        d.add(String(x + w / 2, y + h - 15, title, fontName="Body-Bold", fontSize=9.5, fillColor=INK, textAnchor="middle"))
        for i, line in enumerate(sub):
            d.add(String(x + w / 2, y + h - 28 - i * 11, line, fontName="Body", fontSize=8, fillColor=MUTED, textAnchor="middle"))

    def arrow(x1, y1, x2, y2, label=""):
        d.add(Line(x1, y1, x2, y2, strokeColor=MUTED, strokeWidth=1))
        import math

        a = math.atan2(y2 - y1, x2 - x1)
        p1 = (x2 - 6 * math.cos(a - 0.4), y2 - 6 * math.sin(a - 0.4))
        p2 = (x2 - 6 * math.cos(a + 0.4), y2 - 6 * math.sin(a + 0.4))
        d.add(Polygon([x2, y2, *p1, *p2], fillColor=MUTED, strokeColor=MUTED))
        if label:
            d.add(String((x1 + x2) / 2, (y1 + y2) / 2 + 4, label, fontName="Body", fontSize=7.5, fillColor=MUTED, textAnchor="middle"))

    bw, bh = 38 * mm, 30 * mm
    mx, mw = 58 * mm, 54 * mm  # middle column
    rx, rw = W - 46 * mm, 46 * mm  # right column
    top = 42 * mm
    box(0, top, bw, bh, "Browser", ["User (admin / viewer)", "httpOnly session cookie"])
    box(mx, top, mw, bh, "Next.js frontend  :3000", ["Dashboard pages, charts", "/api/* proxied to backend", "security headers"], fill=colors.HexColor("#F2FAF4"), edge=GREEN)
    box(rx, top, rw, bh, "FastAPI backend  :8010", ["Auth, CSRF, roles", "analytics + reports", "rate limits, audit"], fill=colors.HexColor("#EEF6FB"), edge=BLUE)
    arrow(bw, top + bh / 2, mx, top + bh / 2, "HTTPS")
    arrow(mx + mw, top + bh / 2, rx, top + bh / 2, "/api/v1")

    by = 2 * mm
    box(rx, by, rw, 28 * mm, "Database", ["SQLite (default) or", "PostgreSQL (DATABASE_URL)"])
    box(mx, by, mw, 28 * mm, "Import (ingestion)", ["python-calamine reader", "validation + reconciliation"])
    box(0, by, bw, 28 * mm, "data/raw", ["Master Data …", "Daily track .xlsb"])
    arrow(bw, by + 14 * mm, mx, by + 14 * mm, "upload")
    arrow(mx + mw, by + 14 * mm, rx, by + 14 * mm, "dataset")
    arrow(rx + rw / 2, by + 28 * mm, rx + rw / 2, top, "")
    return d


def dataflow():
    """Excel -> import -> analytics -> API -> pages (left to right)."""
    d = Drawing(174 * mm, 44 * mm)
    steps = [
        ("Excel workbook", ["GP Wise Data", "Master Block · O&M"]),
        ("Import", ["validate rows", "store dataset"]),
        ("Analytics store", ["daily / weekly /", "monthly values"]),
        ("Calculations", ["metrics.py · views.py", "same rules everywhere"]),
        ("API /api/v1", ["JSON per page", "login required"]),
        ("Dashboard", ["KPIs · tables", "line graphs"]),
    ]
    n = len(steps)
    gap = 4 * mm
    w = (174 * mm - gap * (n - 1)) / n
    h = 30 * mm
    y = 7 * mm
    import math

    for i, (title, sub) in enumerate(steps):
        x = i * (w + gap)
        fill = colors.HexColor("#F2FAF4") if i == n - 1 else (colors.HexColor("#EEF6FB") if i in (2, 3) else colors.white)
        d.add(Rect(x, y, w, h, rx=5, ry=5, fillColor=fill, strokeColor=BRAND, strokeWidth=1))
        d.add(String(x + w / 2, y + h - 13, title, fontName="Body-Bold", fontSize=8.6, fillColor=INK, textAnchor="middle"))
        for k, line in enumerate(sub):
            d.add(String(x + w / 2, y + h - 25 - k * 9.5, line, fontName="Body", fontSize=7.2, fillColor=MUTED, textAnchor="middle"))
        if i < n - 1:
            x1, x2, yy = x + w + 0.5, x + w + gap - 0.5, y + h / 2
            d.add(Line(x1, yy, x2, yy, strokeColor=MUTED, strokeWidth=1))
            a = 0.0
            p1 = (x2 - 4 * math.cos(a - 0.5), yy - 4 * math.sin(a - 0.5))
            p2 = (x2 - 4 * math.cos(a + 0.5), yy - 4 * math.sin(a + 0.5))
            d.add(Polygon([x2, yy, *p1, *p2], fillColor=MUTED, strokeColor=MUTED))
    d.add(String(0, 0, "A new workbook goes through the same path: it becomes live only after a successful import.", fontName="Body", fontSize=7.5, fillColor=MUTED))
    return d


def on_page(canvas, doc):
    canvas.saveState()
    if doc.page > 1:
        canvas.setFillColor(GREEN)
        canvas.rect(0, A4[1] - 3, A4[0] / 2, 3, stroke=0, fill=1)
        canvas.setFillColor(BLUE)
        canvas.rect(A4[0] / 2, A4[1] - 3, A4[0] / 2, 3, stroke=0, fill=1)
        canvas.drawImage(str(WORDMARK), 18 * mm, A4[1] - 14 * mm, width=22 * mm, height=22 * mm * 67 / 240, mask="auto")
        canvas.setFont("Body", 8.5)
        canvas.setFillColor(MUTED)
        canvas.drawRightString(A4[0] - 18 * mm, A4[1] - 12 * mm, "Network Analytics – Project Report")
        canvas.drawString(18 * mm, 10 * mm, "Confidential – internal project documentation · 11 Oct 2026")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
    canvas.restoreState()


# ======================================================================= COVER
story.append(Spacer(1, 30 * mm))
story.append(Image(str(LOGO), width=60 * mm, height=60 * mm, hAlign="LEFT"))
story.append(Spacer(1, 6 * mm))
story.append(P('<font name="Body-Bold" size="28" color="#0E1726">Network Analytics Dashboard</font>', "body"))
story.append(Spacer(1, 4 * mm))
story.append(P('<font size="15" color="#5B6675">Project report – architecture, every page and number on the dashboard, how each figure is calculated, security, APIs and verification</font>', "body"))
story.append(Spacer(1, 14 * mm))
story.append(
    table(
        [
            ["Item", "Details"],
            ["Project", "Fibre network operations &amp; analytics dashboard (Rajasthan, Haryana, Assam)"],
            ["Data source", "Master Data V8.2 Daily track 09-10-26.xlsb (data up to 08 Oct 2026)"],
            ["Technology", "Next.js 16 + React 19 + TypeScript (frontend) · Python FastAPI + pandas + SQLAlchemy (backend)"],
            ["Location", r"E:\PRATAP\BSNL  (frontend\, backend\, data\raw\, docs\)"],
            ["Report date", "11 October 2026 (updated after the page redesigns)"],
            ["Status", '<font color="#0B6E2C"><b>All checks passed</b></font> – 27/27 automated tests, lint, type-check and live browser checks'],
        ],
        [35 * mm, 139 * mm],
        bold_first_col=True,
    )
)
story.append(PageBreak())

# ======================================================================= 1 SUMMARY
story.append(H1("1. Executive summary"))
story.append(
    P(
        "The project turns the weekly <b>Master Data … Daily track</b> Excel workbook into a secure web dashboard. "
        "An administrator uploads the workbook; the Python backend reads it, validates every row, stores it in a database and "
        "computes all figures. The Next.js dashboard shows them as KPI cards, charts and tables, from state level down to a single Gram Panchayat (GP), "
        "and produces a weekly management report as PDF."
    )
)
story.append(
    stat_tiles(
        [
            ("16,323", "GPs imported (0 rejected)"),
            ("3 / 601", "states / blocks"),
            ("797,566", "availability values"),
            ("30 + 10", "exact matches + explained"),
            ("0", "unexplained mismatches"),
        ]
    )
)
story.append(H3("What was delivered"))
story.append(
    bullets(
        [
            "<b>Frontend</b> – 7 dashboard pages + login, Google-Analytics/Cloudflare style design, Pratap branding, animated preloader, light/dark theme, search (Ctrl+K), responsive layout. The four analytics pages (Circle Overview, Circle Insights, Block Insights, GP Insights) were redesigned to the O&amp;M report layout: KPI cards, report tables with a table ↔ line-graph flip, and drill-down dropdowns.",
            "<b>Backend</b> – FastAPI service with 24 API endpoints, Excel import with validation, analytics engine, reconciliation against the workbook’s own summary, server-side PDF reports, user management and audit log.",
            "<b>Security</b> – Argon2 password hashing, signed httpOnly session cookie, CSRF protection, role-based access, rate limiting, account lockout, upload checks, security headers, privacy (no phone numbers imported).",
            "<b>Accuracy</b> – every summary number of the workbook’s O&amp;M sheet was recomputed from GP-level data and compared automatically: 30 exact matches, 10 explained differences, 0 unexplained.",
            "<b>Verification</b> – 27 automated tests (13 security + 14 accuracy), frontend lint and type-check, and live checks of every page in a real browser.",
            "<b>Loading experience</b> – while data loads, every KPI card, chart and table shows a moving placeholder with a spinner and “Loading…”, and a thin bar runs along the top of the screen – the page is never blank.",
        ]
    )
)
story.append(H3("Timeline of the work"))
story.append(
    table(
        [
            ["Step", "Work done"],
            ["1. Prompt", "Refined the frontend prompt: GA4/Cloudflare-style clean UI, logo, preloader, uncluttered KPIs."],
            ["2. Frontend", "Built the Next.js dashboard with centralised demo data, all pages, charts, tables, report preview."],
            ["3. Data study", "Moved the workbook to data\\raw\\, analysed its 10 sheets and reverse-engineered the formulas (weeks, MTD, bands, penalty threshold)."],
            ["4. Backend", "Built the FastAPI backend: import, database, analytics, reconciliation, PDF, security, users, audit."],
            ["5. Integration", "Connected the frontend to the backend (proxy, real login, live data, admin pages: upload, accuracy check, users)."],
            ["6. Verification", "Automated tests, live endpoint checks, browser end-to-end checks, first report."],
            ["7. Redesign", "Rebuilt Circle Overview, Circle Insights, Block Insights and GP Insights around the O&amp;M report tables; every figure recomputed from GP rows (not copied from the O&amp;M sheet)."],
            ["8. Polish", "Line graphs for uptime, drill-down dropdowns (state → block → GP), non-AMC GP list, OLT distribution, clear loading states, this updated report."],
        ],
        [30 * mm, 144 * mm],
        bold_first_col=True,
    )
)

# ======================================================================= 2 ARCHITECTURE
story.append(PageBreak())
story.append(H1("2. Architecture"))
story.append(
    P(
        "The browser only talks to the Next.js server. Requests to <font name='Mono'>/api/*</font> are forwarded (proxied) to the Python backend, "
        "so the session cookie stays first-party and can be httpOnly. The backend is the only component that reads the database and enforces security."
    )
)
story.append(architecture())
story.append(Spacer(1, 6))
story.append(H3("How a number reaches the screen"))
story.append(
    P(
        "Every figure follows one path. The workbook is imported once; the backend keeps the GP rows and every daily, weekly and monthly "
        "availability value in memory, and the calculation code builds exactly the payload each page needs. The frontend never recalculates – it only displays."
    )
)
story.append(dataflow())
story.append(Spacer(1, 4))
story.append(H3("Which page uses which endpoint"))
story.append(
    table(
        [
            ["Page", "Endpoint", "Main payload parts"],
            ["Every page", "GET /meta, /notifications, /search", "Weeks, states, districts, blocks, data date; alerts; Ctrl+K search"],
            ["Circle Overview", "GET /overview", "summary, stateDetails, area managers, HOTO by state, NP / closed"],
            ["Circle Insights", "GET /circles/{id}/insights", "summary, blocks, periodTable (HOTO/AMC + GP &amp; block bands), daily bands"],
            ["Block Insights", "GET /blocks/{id}/insights", "summary, gpUptime (bands per period + per day), amcGroups, GPs with OLT"],
            ["GP Insights", "GET /gps?block=…, GET /gps/{code}", "GP list for the dropdown; GP detail with uptime (days in each band)"],
            ["Management Reports", "GET /reports/weekly (+ .pdf)", "Weekly report data and server-generated PDF"],
            ["Data Operations · Settings", "/ingestion/*, /users, /audit", "Admin only: upload, import history, accuracy check, users"],
        ],
        [36 * mm, 52 * mm, 86 * mm],
        bold_first_col=True,
    )
)
story.append(H3("Folder structure"))
story.append(
    Preformatted((
        "E:\\PRATAP\\BSNL<br/>"
        "├─ data\\raw\\          source workbook (git-ignored, never public)<br/>"
        "├─ data\\uploads\\      workbooks uploaded from the dashboard (random names)<br/>"
        "├─ backend\\           Python API<br/>"
        "│  ├─ app\\ingestion\\  reader, parser, validation, import service<br/>"
        "│  ├─ app\\analytics\\  store.py (data in memory), metrics.py (rules), views.py (page payloads),<br/>"
        "│  │                  reconcile.py (accuracy check)<br/>"
        "│  ├─ app\\api\\        auth.py, analytics.py, admin.py<br/>"
        "│  ├─ app\\security\\   passwords, JWT session, CSRF, rate limits, middleware<br/>"
        "│  ├─ app\\reports\\    server-side PDF<br/>"
        "│  ├─ tests\\          security + accuracy tests<br/>"
        "│  └─ var\\app.db      SQLite database (git-ignored)<br/>"
        "├─ frontend\\          Next.js dashboard<br/>"
        "│  ├─ src\\app\\        routes: /login, /dashboard (+ circle-, block-, gp-insights, reports, ...)<br/>"
        "│  ├─ src\\features\\   one folder per page (overview, circle-insights, block-insights, gp-insights ...)<br/>"
        "│  ├─ src\\components\\ shared UI: KPI cards, charts, tables, filters, loading states<br/>"
        "│  └─ src\\lib\\        API client + contracts, formatting, loading tracker<br/>"
        "└─ docs\\              this report"
        ).replace("<br/>", "\n"),
        S["mono"],
    )
)
story.append(H3("Technology"))
story.append(
    table(
        [
            ["Layer", "Technology", "Purpose"],
            ["Frontend", "Next.js 16, React 19, TypeScript, Tailwind CSS v4, Radix UI (shadcn style)", "Pages, layout, components"],
            ["Charts / tables", "Apache ECharts 6, TanStack Table v9", "Interactive charts, sortable/searchable tables"],
            ["Forms", "React Hook Form + Zod", "Login and settings validation"],
            ["Backend", "Python 3.14, FastAPI, Uvicorn, Pydantic", "REST API, validation"],
            ["Data", "pandas, numpy, python-calamine, SQLAlchemy 2", "Excel import (≈2 s read), analytics, database"],
            ["Security", "Argon2 (argon2-cffi), PyJWT", "Password hashing, signed sessions"],
            ["Reports", "ReportLab", "Server-side weekly report PDF"],
            ["Database", "SQLite (default) / PostgreSQL", "Stores datasets, users, audit log"],
        ],
        [28 * mm, 82 * mm, 64 * mm],
        bold_first_col=True,
    )
)

# ======================================================================= 3 DATA
story.append(PageBreak())
story.append(H1("3. Data import (ingestion)"))
story.append(
    P(
        "The workbook has 10 sheets. Three are used: <b>GP Wise Data</b> (one row per GP – the source of truth), "
        "<b>Master Block</b> and the <b>KEY NUMBERS</b> block of the <b>O&amp;M</b> sheet (both only for the accuracy check). "
        "Columns are found by their header text, not by position, so a future version (V8.3 …) with moved columns still imports."
    )
)
story.append(H3("What is imported from GP Wise Data"))
story.append(
    table(
        [
            ["Group", "Columns"],
            ["Hierarchy", "Circle, BA, District, Block, Block Code, GP, GP Code (unique id), Location Code"],
            ["Status", "Converted to NP &amp; Closed, GP Type, Phase, Lot, Block HoTo Status"],
            ["Dates", "HOTO Date, AMC Date, LMS/AMC Date, Letter submission date; AMC / Incremental category"],
            ["Fibre", "BBNL Live KM, BSNL Live KM, TOTAL RKM; OLT Location"],
            ["Availability", "Monthly (Apr–Oct, all GPs), monthly AMC (May–Oct), weekly W-36…W-41, daily 1 Sep – 8 Oct"],
            ["People", "AM Name only (for area-manager performance)"],
            ["Not imported", "<b>Phone numbers and names of splicers, FEs, SHQ SPOC</b> – personal data is deliberately left out"],
        ],
        [30 * mm, 144 * mm],
        bold_first_col=True,
    )
)
story.append(H3("Import process"))
story.append(
    bullets(
        [
            "File type check (.xlsb/.xlsx/.xlsm) and content check (real Excel/ZIP signature), size limit 60 MB.",
            "Every row is validated; bad values are never guessed – they are stored as NA and logged as an issue with the Excel row number.",
            "The import creates a new <i>dataset</i>. It becomes active only after it succeeded; until then the previous data stays live. The last 3 datasets are kept.",
            "Reporting weeks are read from the file itself (e.g. W-41 = 2–8 Oct 2026, Friday–Thursday) – no calendar assumption.",
            "Speed: the 7 MB workbook is read in about 2 seconds and fully imported in about 30 seconds.",
        ]
    )
)
story.append(H3("Data-quality checks (result for the current file)"))
story.append(
    table(
        [
            ["Check", "Severity", "Found"],
            ["OLT location is a date or a number (e.g. 17-07-2026, 0)", "Warning", "197"],
            ["BSNL + BBNL ≠ TOTAL RKM (TOTAL RKM is used)", "Warning", "27"],
            ["AMC date present but HOTO date missing (Assam)", "Warning", "6"],
            ["Negative / non-numeric fibre value", "Warning", "1"],
            ["OLT location missing", "Info", "7,380"],
            ["AM name missing or '0'", "Info", "8,699"],
            ["Duplicate GP codes · rows without GP code · availability outside 0–100%", "Critical", "0"],
        ],
        [120 * mm, 26 * mm, 28 * mm],
    )
)
story.append(P("All issues are listed per Excel row in <b>Data Operations → Data-quality issues</b>.", "small"))

# ======================================================================= 4 ACCURACY
story.append(PageBreak())
story.append(H1("4. Metric definitions and accuracy"))
story.append(
    P(
        "All formulas were reverse-engineered from the workbook and verified value by value. They live in one place "
        "(<font name='Mono'>backend/app/analytics/metrics.py</font>); the frontend only displays results."
    )
)
story.append(
    table(
        [
            ["Metric", "Rule used"],
            ["Total existing GPs", "Rows of GP Wise Data (incl. converted/closed GPs)"],
            ["Revised existing GPs", "Minus Converted to Nagar Palika, Permanently Closed, GP deduction during portal entry"],
            ["HOTO done GPs / blocks", "HOTO date ≤ week end / blocks with at least one such GP"],
            ["AMC GPs · Incremental", "AMC date ≤ week end · category = Incremental"],
            ["AMC GP %", "AMC GPs ÷ revised existing GPs (changes shown in percentage points)"],
            ["Total scope fibre · AMC fibre", "Σ TOTAL RKM of all rows · Σ TOTAL RKM of AMC GPs"],
            ["MTD availability", "Mean of daily values from max(1st of month, GP’s AMC date) up to the week end – same as the workbook formulas"],
            ["Weekly availability", "The workbook’s weekly W-nn columns"],
            ["GPs ≥98% · at 0% · NA", "AMC GPs with value ≥ 98 · = 0 · not reported. <b>NA is never counted as 0%</b>"],
            ["Penalty-prone blocks", "Block mean AMC availability <b>&lt; 90%</b> (source: “Penalty Prone Blocks &lt;90%”)"],
            ["Availability bands", "0%, 0–30, 30–50, 50–75, 75–85, 85–90, 90–95, 95–98, &gt;98% – lower bound included, upper excluded; exactly 98% stays in 95–98; the top band is strictly above 98% (verified against the O&amp;M tables)"],
            ["Total GPs (existing + new)", "Existing = GP Wise Data rows; new GPs come only from the Master Block sheet (they are not listed GP-wise)"],
            ["AMC (original) · Incremental · Non-AMC", "AMC GPs not incremental · AMC GPs marked Incremental · revised existing GPs not yet under AMC – the three always add up to revised existing GPs"],
            ["Month column", "The workbook’s own monthly AMC column of each GP (e.g. “Sep'26 (AMC)”)"],
            ["Month to date (TD)", "Mean of daily values from max(1st of month, AMC date) up to the data date"],
            ["Week column", "The workbook’s weekly W-nn column; a GP counts from its AMC date"],
            ["Block value", "Average of the block’s AMC GPs for that column; blocks counted = blocks with HOTO done by the column end"],
            ["RFP target", "75% of existing GPs by the 4th AMC month (shown in the HOTO / AMC table)"],
            ["Days in each band (GP page)", "For one GP: number of days in the period spent in each band, counted from the daily sheet over the days it was under AMC. Shown only where the daily sheet covers the whole period (it starts 1 Sep 2026)"],
        ],
        [45 * mm, 129 * mm],
        bold_first_col=True,
    )
)
story.append(H3("Reconciliation against the workbook’s O&amp;M sheet (W-41)"))
story.append(
    table(
        [
            ["Figure (O&amp;M KEY NUMBERS)", "Rajasthan", "Haryana", "Assam", "Result"],
            ["Total blocks", "314 / 314", "142 / 142", "145 / 145", "Match"],
            ["Total existing GPs", "8,746 / 8,746", "6,082 / 6,082", "1,495 / 1,495", "Match"],
            ["Revised existing GPs", "8,425 / 8,425", "6,082 / 6,082", "1,471 / 1,471", "Match"],
            ["HOTO done – blocks", "314 / 314", "142 / 142", "133 / 133", "Match"],
            ["HOTO done – GPs", "8,425 / 8,425", "6,082 / 6,082", "1,337 / 1,337", "Match"],
            ["AMC GPs (total)", "4,710 / 4,710", "1,949 / 1,949", "82 / 82", "Match"],
            ["Incremental GPs", "1,235 / 1,235", "305 / 305", "30 / 30", "Match"],
            ["AMC fibre RKM", "30,195.88 / same", "5,394.60 / same", "356.32 / same", "Match"],
            ["GPs at 0% (MTD)", "9 / 4", "329 / 315", "17 / 17", "Explained*"],
            ["GPs above 98% (MTD)", "3,506 / 3,372", "530 / 533", "26 / 25", "Explained*"],
            ["Penalty-prone blocks &lt;90%", "57 / 54", "116 / 117", "29 / 29", "Explained*"],
            ["One-time-up GPs (Sept-26)", "5,641 / 5,633", "2,046 / 2,050", "141 / 138", "Explained**"],
        ],
        [50 * mm, 32 * mm, 30 * mm, 30 * mm, 32 * mm],
        bold_first_col=True,
    )
)
story.append(P("Values are “O&amp;M sheet / dashboard”. Full list (42 rows) is in Data Operations → Accuracy check.", "small"))
story.append(
    callout(
        "<b>* Why the MTD figures differ:</b> in the workbook the “Oct'26 (AMC)” column averages only <b>1–6 Oct</b>, although daily data is "
        "available up to <b>8 Oct</b>. Recomputed for 1–6 Oct, the dashboard gives exactly the O&amp;M values (3,506 / 530 / 26 and 9 / 329 / 17). "
        "The dashboard shows the up-to-date position (to 8 Oct).<br/>"
        "<b>** One-time-up:</b> the O&amp;M figure is typed in from an external report; the dashboard counts GPs with September availability &gt; 0% (difference 3–8 GPs per state).",
        "warn",
    )
)
story.append(
    callout(
        "<b>MTD vs weekly comparison:</b> W-40 ends on 1 Oct, so its month-to-date covers a single day. For like-for-like week comparison the dashboard also "
        "shows <b>(Week)</b> metrics based on the weekly columns – these match the O&amp;M weekly uptime table exactly "
        "(e.g. Rajasthan GPs ≥98%: W-41 3,423 · W-40 3,340 · W-39 3,249). The management report compares weeks on this weekly basis."
    )
)

# ======================================================================= 5 FEATURES
story.append(PageBreak())
story.append(H1("5. What the dashboard shows – page by page"))
story.append(
    P(
        "All analytics pages share one pattern: a row of KPI cards at the top, then report tables in the same layout as the O&amp;M sheet. "
        "A round <b>Graph →</b> button on the right of a table flips it into a line graph and <b>← Table</b> flips it back. "
        "Month &amp; week tables can be switched to <b>Day-wise</b> for the current week. Dropdowns let the user drill down: state → block → GP."
    )
)

story.append(H2("5.1 Circle Overview (home page)"))
story.append(P("The whole network at a glance – all states together, with a dropdown to open any state."))
story.append(
    table(
        [
            ["KPI card", "What it shows"],
            ["Total States / Circles", "Number of states with the state names"],
            ["Total Blocks", "Blocks in the network, split per state"],
            ["Total GPs", "Existing + new GPs, with revised existing GPs (after NP / closed / deducted)"],
            ["HOTO Done Blocks · HOTO Done GPs", "Handed-over blocks and GPs, with how many are pending"],
            ["AMC GPs", "AMC (original), Incremental and Non-AMC with shares"],
            ["GPs Above 98% (MTD) · GPs at 0% (MTD)", "Month-to-date health; NA (not reported) counted separately, never as 0%"],
            ["Penalty-Prone Blocks &lt;90%", "Blocks whose average AMC availability is below 90%, per state"],
            ["Total RKM", "Route kilometres with BSNL and BBNL split"],
        ],
        [55 * mm, 119 * mm],
        bold_first_col=True,
    )
)
story.append(
    bullets(
        [
            "<b>State-wise Comparison</b> – the states side by side on the main figures.",
            "<b>State-wise Network Health</b> – how many GPs of each state are healthy, in the penalty zone, at 0% or not reported.",
            "<b>State-wise HOTO Done</b> – one chart with a Blocks / GPs dropdown.",
            "<b>GPs Converted to NP / Closed</b> – GPs that left the scope, per state.",
            "<b>Area Manager Performance</b> – per area manager: GPs, blocks, revised existing GPs, GPs at 0%.",
        ]
    )
)

story.append(H2("5.2 Circle Insights (one state)"))
story.append(P("Opened from the Overview or the sidebar. An <b>Open a block</b> dropdown jumps straight to Block Insights."))
story.append(
    table(
        [
            ["Section", "What it shows"],
            ["7 KPIs", "Total Districts, Total Blocks, HOTO Done (GPs), HOTO Done Blocks, Total GPs (existing / new / revised), Total Fibre Route (BSNL / BBNL), AMC GPs (AMC / incremental / non-AMC)"],
            ["Block-wise GP Count", "Table of blocks with existing and new GPs; Show Top 10 / 20 / 50 / All"],
            ["HOTO / AMC Status", "Report table: last 4 months, current month to date, Till W-41 and the 3 previous weeks – HOTO done blocks and GPs, AMC GPs, AMC fibre RKM, RFP target. Flips to a line graph (GPs / Blocks / RKM)"],
            ["GP Uptime Performance", "How many AMC GPs fall in each of the 9 availability bands per month, month to date and week, plus totals, NA and average. Day-wise view for the current week. Flips to a line graph with View (Week / Month / Day) and Show (any band, below 90%, average) dropdowns and the latest change ▲ / ▼"],
            ["Block Uptime Performance", "The same table and graph for blocks (block value = average of its AMC GPs)"],
        ],
        [42 * mm, 132 * mm],
        bold_first_col=True,
    )
)

story.append(H2("5.3 Block Insights (one block)"))
story.append(P("Filters: Circle / State, Block (all blocks of the state), <b>Open a GP</b> (jumps to GP Insights with the GP already selected) and Compare week."))
story.append(
    table(
        [
            ["Section", "What it shows"],
            ["Total GPs", "Existing + new GPs of the block (new GPs from the Master Block row), revised existing GPs"],
            ["Total Fibre Route", "Total RKM with BSNL and BBNL RKM and their shares; AMC fibre RKM"],
            ["HOTO Done", "Done and pending GPs with a progress bar"],
            ["AMC GPs + View GP list", "AMC / Incremental / Non-AMC counts; the <b>View GP list</b> dropdown lists the GPs of each group (Non-AMC shows HOTO status and date; AMC shows AMC date and MTD availability). The lists are built with the same rules as the counts, so they always add up"],
            ["GP Uptime Performance", "Bands × periods table for the block’s AMC GPs (as on Circle Insights), Day-wise view, and line graph"],
            ["OLT Distribution", "One bar per OLT location with the number of GPs and share of the block; GPs without an OLT recorded are shown in grey; hover shows the GP names"],
        ],
        [42 * mm, 132 * mm],
        bold_first_col=True,
    )
)

story.append(H2("5.4 GP Insights (one Gram Panchayat)"))
story.append(P("Filters: Circle, District, Block and Gram Panchayat. The page header shows the GP name, LGD code and lifecycle status."))
story.append(
    table(
        [
            ["Section", "What it shows"],
            ["Total Fibre Route", "TOTAL RKM with BSNL and BBNL RKM and shares"],
            ["Availability", "Month to date (coloured: green &gt;98%, amber 90–98%, red &lt;90%) with this week, last week, last month and the block average. Non-AMC GPs show “Not under AMC”, never 0%"],
            ["HOTO status", "Done (with date), Pending or Not applicable"],
            ["AMC / Incremental", "AMC (original), Incremental or Non-AMC with the AMC date"],
            ["OLT location · Phase · LOT", "As recorded in GP Wise Data; blanks shown as “Not recorded”"],
            ["GP Uptime Performance", "Same band layout, but each cell is the <b>number of days</b> the GP spent in that band in the period; footer: days with value, NA days, the GP’s own value and the block’s value. Day-wise view shows the band of each day. Months before 1 Sep 2026 show “–” because the workbook has no daily values for them"],
            ["Graph", "The GP’s availability line against the block average (dashed) with the 90% penalty line"],
        ],
        [42 * mm, 132 * mm],
        bold_first_col=True,
    )
)

story.append(H2("5.5 Other pages and shared features"))
story.append(
    table(
        [
            ["Page / feature", "What it does"],
            ["Login", "Email + password, show/hide password, remember me, validation, friendly errors, session-expired notice, safe redirect after login."],
            ["Preloader", "Pratap logo with an animated green→blue “fibre light”, shown once per browser session; respects reduced-motion settings."],
            ["Loading states", "Moving placeholder + spinner + “Loading…” in every KPI card, chart and table, and a thin animated bar at the top while any data loads."],
            ["Management Reports", "Filters (state, district, block, week, compare week); report preview with executive summary, KPI comparison (pp for %), ranking, HOTO, fibre, penalty blocks, low-availability GPs, data quality; <b>Download PDF</b> (server-generated) and Print."],
            ["Data Operations (admin)", "Upload a new workbook, live processing status, import history, retry, accuracy check table, data-quality issues by severity."],
            ["Settings (admin)", "Data environment, theme, change password, user management (add user, enable / disable)."],
            ["Everywhere", "Ctrl+K search (states, blocks, GPs, LGD codes), notifications, week selector, reload, light / dark theme, breadcrumbs, mobile layout, filters kept in the URL."],
        ],
        [36 * mm, 138 * mm],
        bold_first_col=True,
    )
)
story.append(H3("Display rules applied everywhere"))
story.append(
    bullets(
        [
            "NA (not reported) is shown as “NA” and is never counted as 0%; “—” means not under AMC in that period.",
            "Percentage changes are shown in percentage points (pp); fibre values are labelled RKM.",
            "GPs are counted once (unique GP codes) – daily snapshots are never summed.",
            "Colours carry meaning consistently: green = healthy (&gt;98%), amber = watch (90–98%), red = penalty-prone (&lt;90%).",
            "Every table states its period, and every graph can be flipped back to the exact numbers.",
        ]
    )
)

# ======================================================================= 6 SECURITY
story.append(PageBreak())
story.append(H1("6. Security"))
story.append(
    P("Security is enforced on the server. The frontend checks only improve usability – every request is checked again by the backend.")
)
story.append(
    table(
        [
            ["Area", "Measure"],
            ["Passwords", "Argon2id hashing (memory-hard); policy ≥ 12 characters with 3 character types; no default or hard-coded accounts; automatic re-hashing."],
            ["Sessions", "Signed JWT (HS256, algorithm pinned, issuer/audience/expiry checked) in an <b>httpOnly, SameSite=Lax</b> cookie (Secure in production); 8-hour lifetime; JavaScript cannot read it."],
            ["Session revocation", "Logout, password change, role change or deactivation increments a token version – all older sessions stop working immediately."],
            ["CSRF", "Double-submit token (cookie + X-CSRF-Token header) required for every POST/PATCH; Origin/Referer allow-list blocks cross-site requests."],
            ["Brute-force", "Login limit per IP and per account (5 attempts / 15 min), account lockout after 10 failures (30 min), same error for unknown email and wrong password, constant-time checks."],
            ["Authorization", "All data endpoints require login; import, accuracy check, users and audit require the <b>admin</b> role (HTTP 403 otherwise)."],
            ["Input validation", "Strict patterns for every id and parameter (week, circle, block, GP code), length limits, Pydantic bodies; error messages never echo submitted values."],
            ["File upload", "Admin only; extension allow-list + Excel signature check; streamed size limit; stored under a random name outside the web root; one import at a time; failed imports never replace live data."],
            ["HTTP hardening", "CSP (default-src 'none'), X-Frame-Options DENY, nosniff, Referrer-Policy, Permissions-Policy, no-store caching, HSTS in production, trusted hosts, CORS allow-list, per-IP rate limit, request ids, no stack traces, API docs disabled in production, X-Powered-By hidden."],
            ["Proxy awareness", "Client IP taken from X-Forwarded-For only when the request comes from the trusted local proxy (Next.js), so rate limits apply per real user."],
            ["Privacy", "Phone numbers / personal names of field staff are not imported; company files are kept outside the apps and excluded from Git."],
            ["Audit log", "Logins (success, failure, lockout, rate-limit), logouts, uploads, retries, user and password changes – with time, user and IP."],
            ["Secrets", "SECRET_KEY generated randomly into backend\\.env (git-ignored); placeholder keys are rejected at start-up."],
        ],
        [32 * mm, 142 * mm],
        bold_first_col=True,
    )
)

# ======================================================================= 7 API
story.append(PageBreak())
story.append(H1("7. API endpoints"))
story.append(
    P(
        "All endpoints are under <font name='Mono'>/api/v1</font> and return JSON. Read endpoints accept <font name='Mono'>week=W-41&amp;compare=W-40</font> "
        "and optional <font name='Mono'>circle</font>, <font name='Mono'>district</font>, <font name='Mono'>block</font>. "
        "Access: <b>Public</b> = no login · <b>User</b> = any signed-in user · <b>Admin</b> = admin role. POST/PATCH also need the CSRF token."
    )
)
api_rows = [
    ["Method", "Path", "Access", "Purpose"],
    ["GET", "/api/health", "Public", "Health check (returns only “ok”)"],
    ["POST", "/auth/login", "Public", "Sign in; sets session + CSRF cookies (rate-limited)"],
    ["POST", "/auth/logout", "User", "Sign out and revoke all sessions"],
    ["GET", "/auth/me", "User", "Current user (name, email, role)"],
    ["POST", "/auth/change-password", "User", "Change own password (policy enforced)"],
    ["GET", "/meta", "User", "Weeks, states, districts, blocks, data-as-of date, thresholds"],
    ["GET", "/overview", "User", "Circle Overview KPIs, state summaries, area managers"],
    ["GET", "/circles/{id}/insights", "User", "Circle Insights: KPIs, blocks, HOTO/AMC, uptime bands"],
    ["GET", "/blocks/{id}/insights", "User", "Block Insights: KPIs, GPs, OLTs, trends, categories"],
    ["GET", "/gps", "User", "GP list with search and server pagination"],
    ["GET", "/gps/{code}", "User", "GP detail: daily/weekly/monthly history, timeline, issues"],
    ["GET", "/search?q=", "User", "Search states, blocks, GPs, LGD codes"],
    ["GET", "/reports/weekly", "User", "Weekly management report data"],
    ["GET", "/reports/weekly.pdf", "User", "Weekly management report as PDF"],
    ["GET", "/notifications", "User", "Alerts (penalty blocks, 0% GPs, NA, data date)"],
    ["GET", "/ingestion/runs", "Admin", "Import history and status"],
    ["GET", "/ingestion/runs/{id}/issues", "Admin", "Data-quality issues of an import (filter by severity)"],
    ["POST", "/ingestion/upload", "Admin", "Upload a new workbook (processed in background)"],
    ["POST", "/ingestion/runs/{id}/retry", "Admin", "Re-process a failed / partial import"],
    ["GET", "/ingestion/reconciliation", "Admin", "Accuracy check vs O&amp;M KEY NUMBERS"],
    ["GET", "/users", "Admin", "List users"],
    ["POST", "/users", "Admin", "Create user (admin / viewer)"],
    ["PATCH", "/users/{id}", "Admin", "Change name, role, enable/disable, reset password"],
    ["GET", "/audit", "Admin", "Audit log"],
]
story.append(table(api_rows, [16 * mm, 52 * mm, 18 * mm, 88 * mm]))
story.append(P("Interactive API documentation: http://127.0.0.1:8010/docs (development mode only).", "small"))

# ======================================================================= 8 VERIFICATION
story.append(PageBreak())
story.append(H1("8. Verification results (11 Oct 2026)"))
story.append(callout("<b>Result: everything checked is working correctly.</b> No failing test, no type or lint error, no console error, and no unexplained data difference. Browser tests used temporary viewer accounts that were deleted afterwards.", "good"))
story.append(H3("Automated backend tests – 27 / 27 passed"))
story.append(
    table(
        [
            ["Security tests (13)", "Accuracy tests (14)"],
            [
                "Health endpoint public + security headers · all data endpoints need a session · generic login errors (no user enumeration) · "
                "login rate limit · httpOnly/SameSite cookie · CSRF required · logout revokes old token · forged and “alg=none” tokens rejected · "
                "viewer blocked from admin endpoints · cross-site POST blocked · weak password rejected · non-Excel uploads rejected · malicious ids rejected",
                "Structural numbers match O&amp;M for Rajasthan, Haryana, Assam (3 tests) · MTD with the source date range reproduces O&amp;M exactly · "
                "weekly bands match O&amp;M exactly · no unexplained reconciliation mismatch · NA never counted as 0 · API payloads + PDF · "
                "upload → background import → activation (with path-traversal file name) · Circle Overview summary matches the workbook · "
                "Circle Insights for Rajasthan · period table matches O&amp;M (Jun/Aug/Sep/Till W-41/WK-40 bands, HOTO/AMC) · "
                "block KPIs, AMC groups and GP-wise uptime recomputed from GP rows · GP uptime equals its MTD / weekly values and the block view, "
                "days-in-band add up and a full week has 7 days",
            ],
        ],
        [87 * mm, 87 * mm],
    )
)
story.append(H3("Live checks on the running system"))
story.append(
    table(
        [
            ["Check", "Result"],
            ["22 protected endpoints called without login", "All returned 401 (not authenticated)"],
            ["Cross-site login request (foreign Origin)", "403 – blocked"],
            ["Request with an untrusted Host header", "400 – blocked"],
            ["Security headers on API and frontend", "Present (CSP, X-Frame-Options, nosniff, Referrer-Policy, Permissions-Policy, no-store)"],
            ["Frontend: /dashboard without login", "307 redirect to /login"],
            ["Browser test as viewer: all user pages", "Rendered with real data (e.g. 17,980 GPs incl. 1,657 new, AMC 42.2%, &gt;98% MTD 3,930)"],
            ["Drill-down", "Circle → Open a block → Block Insights; Block → Open a GP → GP Insights with the GP pre-selected"],
            ["Block Insights (Abu Road)", "AMC 2 · Incremental 7 · Non-AMC 23 – the GP lists show exactly 2 / 7 / 23 GPs"],
            ["GP Insights (Gorchiya Ka Bera)", "Oct TD 76.90% = 6 days &gt;98% + 1 day 0–30% + 1 day 0%; Sep daily mean 85.13% equals the workbook column"],
            ["Loading with a slow network", "Placeholders, spinners and the top bar are visible until the data arrives – no blank page"],
            ["Viewer opens admin page / admin API", "“Admins only” shown · API returned 403"],
            ["Report PDF download", "Generated by the backend (valid PDF)"],
            ["After logout", "API returned 401 – session revoked"],
            ["Browser console errors / failed requests", "None"],
            ["Frontend lint · TypeScript", "0 problems · 0 errors"],
            ["Reconciliation (42 figures)", "30 match · 10 explained · 2 no reference value · 0 unexplained"],
        ],
        [75 * mm, 99 * mm],
        bold_first_col=True,
    )
)

# ======================================================================= 9 OPERATIONS
story.append(PageBreak())
story.append(H1("9. How to run and operate"))
story.append(H3("Start the system (two terminals)"))
story.append(
    Preformatted((
        "# Terminal 1 - backend  (http://127.0.0.1:8010)<br/>"
        "cd E:\\PRATAP\\BSNL\\backend<br/>"
        ".\\start.ps1<br/><br/>"
        "# Terminal 2 - dashboard  (http://localhost:3000)<br/>"
        "cd E:\\PRATAP\\BSNL\\frontend<br/>"
        "npm run dev"
        ).replace("<br/>", "\n"),
        S["mono"],
    )
)
story.append(H3("Everyday tasks"))
story.append(
    table(
        [
            ["Task", "How"],
            ["Weekly data update", "Sign in as admin → Data Operations → <b>Upload master data</b> → wait for “Success” → check the Accuracy check table."],
            ["Add a user", "Settings → Users → name, email, role, initial password → Add user. Or: <font name='Mono'>python -m app.cli create-user</font>"],
            ["Disable a user", "Settings → Users → Disable (their sessions end immediately)."],
            ["Change your password", "Settings → Change your password."],
            ["Weekly report", "Management Reports → choose week and comparison → Download PDF."],
            ["Run the tests", "<font name='Mono'>cd backend; .\\.venv\\Scripts\\python -m pytest -q</font>"],
            ["Check accuracy from the command line", "<font name='Mono'>python -m app.cli reconcile</font>"],
        ],
        [42 * mm, 132 * mm],
        bold_first_col=True,
    )
)
story.append(H3("Configuration (backend\\.env)"))
story.append(
    table(
        [
            ["Setting", "Default", "Meaning"],
            ["APP_ENV", "development", "production = secure cookies, HSTS, API docs off"],
            ["SECRET_KEY", "random (generated)", "Signs sessions – keep secret, never share"],
            ["DATABASE_URL", "SQLite var\\app.db", "Set a PostgreSQL URL for production"],
            ["CORS_ORIGINS / TRUSTED_HOSTS", "localhost", "Add the real domain when deployed"],
            ["PENALTY_THRESHOLD / HEALTHY_THRESHOLD", "90 / 98", "Business thresholds (%)"],
            ["SESSION_TTL_MINUTES", "480", "Session lifetime"],
            ["UPLOAD_MAX_MB", "60", "Maximum workbook size"],
        ],
        [62 * mm, 40 * mm, 72 * mm],
    )
)

# ======================================================================= 10 LIMITS
story.append(PageBreak())
story.append(H1("10. Known limitations and next steps"))
story.append(
    table(
        [
            ["Topic", "Status / recommendation"],
            ["Google Drive automation", "Not built yet – workbooks are uploaded from Data Operations. Can be added as a scheduled job using a Google service account."],
            ["Production hosting", "Run behind HTTPS (Nginx / IIS), set APP_ENV=production and the real domain in CORS_ORIGINS / TRUSTED_HOSTS."],
            ["Database", "SQLite is fine for one server; use PostgreSQL for production and schedule backups."],
            ["Scaling", "Rate limits are kept in memory → run one backend worker, or move limits to Redis for several workers."],
            ["Source data", "Missing AM names (8,699 GPs) and OLT locations (7,380 GPs) limit those views – fixing them in the workbook improves the dashboard automatically."],
            ["Workbook formula", "The workbook’s Oct'26 (AMC) column stops at 6 Oct – worth correcting in the workbook so both show the same MTD."],
            ["Thresholds", "Penalty threshold is 90% as in the workbook (the original brief mentioned 85%) – change PENALTY_THRESHOLD if needed."],
            ["Daily history", "The workbook’s daily sheet starts on 1 Sep 2026, so day counts on GP Insights exist from September onwards; earlier months show only their monthly value."],
            ["Password recovery", "There is no “forgot password” e-mail and no reset button in Settings yet. An admin can set a new password for another user only through the admin API (PATCH /users/{id}). Passwords are stored only as Argon2 hashes and cannot be read back – a reset button for admins is a recommended next step."],
        ],
        [42 * mm, 132 * mm],
        bold_first_col=True,
    )
)

doc = SimpleDocTemplate(
    str(OUT),
    pagesize=A4,
    leftMargin=18 * mm,
    rightMargin=18 * mm,
    topMargin=20 * mm,
    bottomMargin=18 * mm,
    title="Network Analytics Dashboard – Project Report",
    author="Pratap",
    subject="Project documentation: architecture, pages, calculations, security, API, verification",
)
doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
print("written", OUT)

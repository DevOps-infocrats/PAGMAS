# Data uploads – format, storage and validation

Two data files feed the dashboard. Both are uploaded on **Data Operations → Upload data file**: choose the
**file type**, pick the file, read the **check report**, then **Confirm import**. Nothing changes on the
dashboard before the confirm.

Templates (headers only) and samples (2 example rows) are in `frontend/public/templates/` and can be
downloaded from the upload dialog.

## 1. Master Data workbook

| | |
|---|---|
| File type | `.xlsb` or `.xlsx` (macro files `.xlsm` are refused) |
| Sheet | `GP Wise Data` (required); optional: `Master Block`, `O&M`, `Rajasthan` / `Haryana` / `Assam` |
| Header row | found in the first 15 rows (row 3 in the template) by the columns Circle + GP Code + TOTAL RKM |
| Required columns | Circle, District, Block, Block Code, GP, GP Code, TOTAL RKM, HOTO Date, AMC Date |
| Optional columns | BA, Block HOTO Status, Location Code, Converted to NP & Closed, GP Type, Phase, OLT Location, BBNL Live KM, BSNL Live KM, LMS /AMC Date, Lot wise, Letter Submission Date AMC Incremental, AMC / Incremental, AM Name, 5% Contractual Incremental+ Additional AMC, Planned Date, Ach Date, Current Status, Letter Status, Letter submission Date, Approval Status |
| Time-varying columns | detected by pattern, never by a fixed name: monthly = a real date on the 1st of a month (before the weekly columns) · `Mon'YY (AMC)` · `W-nn` with the week dates (`31-6 Nov`) in the row above · daily = real dates, one per day, directly after the last `W-nn` column without gaps |
| Business key | GP Code (unique) |
| Max size | `UPLOAD_MAX_MB` (60 MB) |

Column names are matched case- and space-insensitively; more accepted names can be added on Data Operations →
Column names (`data/column_map.json`) – the importer never guesses a renamed column, it only suggests it.

## 2. Escalation Matrix

| | |
|---|---|
| File type | `.xlsx` or `.xlsb` |
| Sheet | any sheet whose header row has the required columns (`All` in the template) |
| Required columns | Circle, GP Code, FRT Code, FE Name |
| Optional columns | BA, District, Block Name, Block Code, GP, Splicer Name / number, FE Number, FE Email ID, AM Name / Number / Email ID, SME Name / Number / Email ID, COH / No. / Email ID, CBH / No. / Email ID |
| Business key | GP Code (matched to the master data's GP Code) |

A GP without **AM Name** does not appear in Area Manager / FE lists (AM-wise targets, Generate Ticket) – the
check report lists those rows.

The active matrix can also be corrected on **Field Team & Escalation → Escalation Sheet** (admins). Saved cells
change the database at once (with an edit history); a later matrix upload replaces them – export the sheet and
use it as the next upload to keep the corrections.

## Validation – strict order, first failure stops

1. **File** – extension (`.xlsx` / `.xlsb`), not empty, a genuine workbook package (ZIP with `[Content_Types].xml`
   and `xl/workbook.xml` / `xl/workbook.bin` – a renamed file is refused), zip-bomb guard
   (`ZIP_MAX_UNCOMPRESSED_MB`, `ZIP_MAX_RATIO`; a real master file is ~7 MB → ~60 MB, ~9×).
2. **File type** – the content must be the file chosen in the dropdown.
3. **Duplicate** – the same file (SHA-256) imported successfully before is refused.
4. **Structure** – required sheet, required columns, at least one week and one day of data.
5. **Rows** – each row is checked; the report lists every finding **with its Excel row number**:
   * *critical* – the row is rejected (no GP code / circle, duplicate GP code – the message names **both** rows);
   * *warning* – the row is kept, the value is left empty (invalid date, number, e-mail, availability outside
     0–100 %, …);
   * *info* – for information (e.g. OLT location missing).

Data-quality rules: **blank is never 0** (a blank value is "not reported" and stored empty – sums skip it);
values are kept as written (trimmed), never re-mapped silently. The file's own **O&M key numbers** (Total
Blocks, Revised Existing GPs, HOTO Done – GPs) are cross-checked against the rows (warning only). After the
import, Data Operations → Reconciliation compares all key numbers with the dashboard.

The browser filters the file type and size, but the backend checks everything again.

## Where files are stored

```
DATA_DIR/staging/   <token>.<ext> + <token>.json   checked uploads waiting for "Confirm import"
                                                    (deleted on cancel, on a failed check and after STAGING_TTL_MINUTES)
DATA_DIR/uploads/   <UTC timestamp>-<sha256[:16]>.<ext>   confirmed uploads (atomic move from staging)
DATA_DIR/raw/       files imported by the CLI / first start
```

The import parses the confirmed file, writes its rows and switches the active dataset **in one transaction**
(a failed import never replaces the active data). The newest `KEEP_DATASETS` (3) successful imports are kept;
older rows and files are pruned. One import runs at a time.

## Settings (environment variables)

`DATA_DIR`, `DATABASE_URL`, `UPLOAD_MAX_MB` (60), `STAGING_TTL_MINUTES` (60), `ZIP_MAX_UNCOMPRESSED_MB` (1024),
`ZIP_MAX_RATIO` (200), `KEEP_DATASETS` (3).

## API

| Endpoint | |
|---|---|
| `POST /api/v1/ingestion/preview` (form: `file`, `kind` = master \| escalation) | step 1 – stage + validation report (`canImport`, `stage`, `counts`, `facts`, `crossCheck`, `issues` with row numbers, `token`) |
| `POST /api/v1/ingestion/confirm` `{token}` | step 2 – import the staged file (202) |
| `DELETE /api/v1/ingestion/preview/{token}` | cancel – delete the staged file |
| `POST /api/v1/ingestion/upload` (form: `file`, optional `kind`) | one-step upload (scripts) – same checks |
| `GET/PATCH /api/v1/field-team/sheet`, `POST …/sheet/replace`, `GET …/sheet/edits`, `GET …/sheet/export.xlsx` | Escalation Sheet |

Tests: `backend/tests/test_upload_pipeline.py`, `backend/tests/test_escalation_sheet.py`.

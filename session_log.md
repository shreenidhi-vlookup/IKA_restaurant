# SESSION_LOG.md

> that's what lets a brand-new session (with zero memory) understand exactly
> where things left off, just by reading CONTEXT.md -> this file.
---
## Session 27 — 2026-09-28 — Sales report: long slip + Daily Exception Excel, and the Process dashboard
**Context:** resumed an interrupted session. Findings: the Sessions 24/25
**backend** work is real and works (verified by running the server), but the
Sessions 25 **frontend** work was overwritten when Session 26 took `final`'s
`App.jsx` (`ec61170`) and now exists only in `stash@{0}`. The "Upload Excel" /
"Upload long bill slip" controls in the Comparison source panel are present and
clickable but unwired. During this session the requirement changed: **Source 2
is not a mirrored export of the slip.** It is the Excel *Daily Exception
Report*, a row-level log, and the first Session 27 plan (written before that
change) is superseded by the plan below.

**The two sources:**
- **Source 1 — the long slip** (a photo of the till's printed Work Period
  Report): per-department Voids / Discounts / Promotions / Cancelled, count and
  amount. A `-` in a total is zero. Read by vision.
- **Source 2 — the Excel Daily Exception Report** (`.xlsx`): one row per
  voided / discounted / promoted item. Prefer the `Daily Void Log` sheet;
  `Daily Exception Summary` is a void-amount sanity check only, not a
  reconciliation input. `Adjustment Type` starting with `Void` is a void; a
  **blank** `Adjustment Type` is `unfilled` and is **never** counted as a void.
  Bill numbers have all whitespace removed so `260921 - 48` equals
  `260921-48`. Rows are **counted, never deduplicated by bill**. Rows outside the
  selected branch/day are skipped, and the skipped count is reported.

**Planned changes:**
- `app/models/daily_exception.py` (new): parse the Daily Exception log from
  raw `.xlsx`; classify each row `void` / `discount` / `promotion` / `cancelled`
  / `unfilled` / `other`; normalize bill numbers; scope by branch + day.
- `app/models/sales_report.py`: replace the mirrored-CSV comparison with
  `compare_slip_with_excel` (void **amount** is the primary check), plus shared
  date/sheet helpers and one `canonical_date_key` used by every layer.
- `app/storage/db.py`: `sales_reports` carries the Excel filename, summary and
  counters; new `daily_exception_rows` child table, fully replaced with the
  report so a re-upload cannot leave stale rows.
- `app/api/upload.py`: `POST /api/upload/sales-reports` takes `file`,
  `excel_file`, `restaurant`, `report_date`, `confirm`. Both sources together are
  cross-verified **before** storage; a mismatch with no `confirm` returns a
  structured **409** and stores **nothing**; `confirm=slip|excel` then stores the
  operator's chosen source and records it in `confirmed_source`.
- `app/api/sales_report_reconciliation.py`: new `POST /api/sales-reports/process`
  — one backend-owned payload with every dashboard figure, the unmatched ticket
  voids and unmatched dockets as **lists**, per-department and total figures, an
  anomaly flag, the discounts/promotions that are reported but not yet
  reconciled, and a `missing` list naming absent inputs by name.
- `app/api/records.py`: `GET /api/restaurants` so the UI never hardcodes branch
  names or maps till names itself.
- Frontend: wire the **existing** Comparison source controls (no duplicate
  upload UI), add branch + working-day scope, render the 409 as an
  operator-resolved conflict, add a `Process` button and the dashboard rendered
  straight from the Process payload — no client-side matching or counting.
- Docs: `decisions.md`, `MVP_spec.md`, `architecture.md`, `frontend_spec.md`,
  `context.md`, this log. No automated tests; minimal manual checks only.

**Achieved:**
- `app/models/daily_exception.py` created: `Daily Void Log` preferred,
  `Daily Exception Summary` read as a sanity check only, `classify_adjustment`
  (startswith `Void` -> void, blank -> `unfilled`, never a void),
  `normalize_bill_number` (whitespace removed), `bill_number_date_key` (the
  bill's own `YYMMDD` prefix decides the row's day), and `skipped_rows` for
  out-of-scope rows. Verified against a generated workbook: kept 5 Ilford rows,
  skipped 1 Southall row, 2 void rows totalling 13.98, 1 unfilled, 1 discount
  6.99, 1 promotion, and `260921 - 48` and `260921-48` both kept (no dedupe).
- `app/models/sales_report.py`: `canonical_date_key` is now the single date
  implementation shared by the slip, the Excel log, the tickets and the dockets,
  so a day written two ways still joins. `compare_slip_with_excel` makes the void
  **amount** the primary check and reports the void **count** comparison as
  explicitly **not scored** — it is not yet empirically confirmed whether the
  slip counts voided items or voided bills, and one bill can own several void
  rows.
- `app/storage/db.py`: `daily_exception_rows` table; the report upsert replaces
  its rows wholesale; the upsert date comparison now uses `canonical_date_key`
  (it previously compared digit runs, so `22/9/2026` and `2026-09-22` never
  matched and a re-upload created a duplicate row for the same day).
- `app/api/upload.py`: the two-source upload with the 409-before-store rule. A
  working day is now **required** — the slip's own printed date is never used to
  define the day, because a till can print a date that differs from the day the
  report is filed under.
- Ticket day now comes from the **Ticket ID's `YYMMDD` prefix**, with the
  printed date only as a fallback, in both `app/api/void_reconciliation.py` and
  `app/api/sales_report_reconciliation.py`. This matters on the real data: all
  three stored tickets print a date one day ahead of their id prefix
  (`260921-48` prints `22/9/2026`), so the old code filed them under the wrong
  day.
- Excel-bill-found matching is now scoped to the selected branch and day, so a
  bill id that collides with another branch's ticket is not reported as found.
- `GET /api/restaurants` always returns all three branches (Ilford, Southall,
  Norbury), including ones with no tickets yet; it previously hid any branch
  that had no ticket rows.
- `POST /api/sales-reports/process` returns the whole dashboard from stored
  data, recomputed per run, including the named-empty-state `missing` list.
  Fixed a real 500 found by the smoke test: the no-report path returned an
  incomplete Excel shape and raised `KeyError: 'void_bills_found'`.
- Docket counting made honest: the tally pairs on the docket's trailing order
  number, so a matched docket can carry a printed date other than the working
  day. The payload now reports `dockets` (filed on this day) separately from
  `dockets_used_in_matches` and `matched_dockets_filed_on_another_day` instead
  of showing "matched 1" beside "dockets 0".
- Frontend: branch + working-day scope, the two existing source controls wired to
  `uploadSalesReport(imageFile, excelFile, restaurant, reportDate, confirm)`, the
  409 rendered as an operator choice (store the slip / store the Excel), the
  saved-report summary, the `Process` button, and the dashboard: source chips,
  missing-inputs notice, six stat cards, Voids in the long slip, Voids in Excel
  with the bill-by-bill found/not-found table and the unfilled-row warning, the
  Bill vs Excel check, per-department and total reconciliation, both unmatched
  lists, discounts/promotions, and a named empty state for every absent input.
  `upload.js` reads the body itself on a 409 so the UI keeps the structured
  `detail` instead of the flattened string `apiFetch` would produce.
- `frontend`: `oxlint` clean, `vite build` passes. The description modal,
  keyboard navigation, ticket/docket bulk upload and export were left untouched.
- **Verified by hand** (no automated tests, per the task): backend compiles and
  `app.main` imports; `GET /api/restaurants` returns all three branches; an
  Excel-only upload for Ilford 2026-09-22 stored 2 void rows / 13.98 / 1
  unfilled / 1 skipped, and the row whose Date cell says 23 Sep was correctly
  kept as 22 Sep because its bill number says `260922`; a missing working day is
  rejected 400; a branch with no rows is rejected 400 naming 6 skipped rows; a
  both-sources mismatch returns 409 with the structured detail and stores
  nothing (report count and file list unchanged); `confirm=slip` then stores with
  `source="slip (confirmed)"` and `confirmed_source="slip"`; Process returns 200
  for a branch+day with no stored report, with the missing list naming the long
  slip, tickets and dockets.
- **Still open, needs the user:** no real same-day long slip + real Daily
  Exception Report pair has been seen, so the empirical meaning of the slip's
  void count and the final visual acceptance are still unconfirmed. Gemini
  `gemini-2.5-flash` returns HTTP 404 (no longer available to new users); the
  default is now `gemini-3.8-flash`, which answered once, but the
  `extraction_method` fallback to Tesseract+regex is still recorded visibly
  whenever it is used.

## Session 26 — 2026-09-25 — Resolve final frontend pull
**Planned changes:**
- Preserve the incoming `final` branch implementation of `frontend/src/App.jsx` and `frontend/src/App.css` from commit `ec61170`, including description-modal and keyboard-navigation behavior.
- Merge that frontend with the stashed local backend work and session history without discarding either side.
**Achieved:**
- Confirmed `final` was fast-forwarded to `ec61170` and retained the incoming `App.jsx`/`App.css` implementation.
- Resolved the frontend conflicts, preserved the stashed local backend work and session history, and left the stash entry available as a backup.
- Fixed the incoming frontend's missing `getEntries` import and removed redundant effect state updates.
- Removed all conflict markers; `npm run lint` and `npm run build` both pass.

## Session 23 — 2026-09-23
**Planned changes:**
- Replace (add as parallel, vision-first path) plain-OCR extraction with a
  vision-capable Gemini call for the two document types that plain OCR fails
  on: ticket screenshots (struck-through / voided line items are missed or
  garbled) and dockets (handwriting cannot be read as printed text).
- New `app/extraction/vision.py`: stdlib-only Gemini REST client
  (`GEMINI_API_KEY` env, model via `GEMINI_MODEL`, default
  `gemini-2.5-flash`) that sends the actual image bytes with a structured
  JSON prompt, reusing the master parsing field schemas already documented in
  `parse_ticket_screenshot` / `parse_docket_text`.
- Tickets: per-item `is_void` decided from visual styling (strikethrough OR
  an explicit (Void) label), never from literal-text pattern matching alone.
- Dockets: model must separate printed receipt text (goes into the printed
  fields) from handwriting (goes ONLY into `handwritten_reason` / the public
  `description`); `description` stays `null` when a docket has no
  handwriting.
- Wire into `app/api/upload.py` for `/api/upload/tickets`,
  `/api/upload/dockets`, and the structure-detected generic path: vision is
  primary; when no `GEMINI_API_KEY` is present or the API call fails, fall
  back to the existing Tesseract+regex path AND record that the row used OCR
  fallback so the fallback is visible, never silent.
- Add an additive `extraction_method` column (`vision` | `ocr_fallback`) to
  `ticket_records` and `docket_records`; expose it in `/api/tickets` and
  `/api/dockets`; flag docket rows with OCR fallback as `review_required`.
- Verify acceptance on the real samples: ticket `#260921-48` (all 4
  struck-through items → `is_void: true`), a real docket with handwriting
  (description = handwriting only, correctly transcribed), and a mixed
  void/non-void check for false positives.
- Update `decisions.md`, `MVP_spec.md`, `architecture.md`,
  `frontend_spec.md`, `CONTEXT.md`, and this log. No automated tests.

**Achieved (implemented; acceptance still pending a GEMINI_API_KEY):**
- New `app/extraction/vision.py`: stdlib-only Gemini REST client
  (`GEMINI_API_KEY`/`GOOGLE_API_KEY`, `GEMINI_MODEL` default
  `gemini-2.5-flash`) with `vision_available()`,
  `vision_extract_ticket()` (per-item `is_void` from strikethrough OR
  (Void) label), `vision_extract_docket()` -> `(dict, review_flags)`, and
  `vision_extract_sales_report()`.
- Additive `extraction_method` column on `ticket_records`/`docket_records`
  (idempotent ALTER); `upsert_ticket_record` merge rule "vision beats
  ocr_fallback"; `create_docket_record` persists the method; OCR-fallback
  docket rows are flagged `review_required` with an explicit reason.
- `extraction_method` exposed in `/api/tickets`, `/api/dockets`, and both
  CSVs. Verified with `python3 -m py_compile` and the OCR-fallback path only.
- `verify_vision_extraction.py` harness provided (env var or key file arg).
- Acceptance run (ticket `#260921-48`, handwriting docket, mixed
  void/non-void) is BLOCKED on a real key — user to place it at
  `/tmp/opencode/gemini.env`.

## Session 24 — 2026-09-23 — Sales report upload (Division 6)
> Status of Session 23 (vision extraction): code implemented, acceptance
> verification still pending because no GEMINI_API_KEY has been provided yet.
> Carried forward; not part of this session's scope.

## Session 25 — 2026-09-24 — Sales report aggregate reconciliation UI (Division 6)
> Status of Session 24 (sales report upload): code implemented and verified,
> waiting on user for real-sample acceptance.

**Planned changes:**
- Implement missing frontend Sales Report Aggregate Reconciliation UI (Screen 6 per frontend_spec.md)
- Add state management for reconciliation data loading/error states
- Add function to fetch sales report reconciliation data from `/api/sales-reports/reconcile`
- Add UI section to display reported vs matched vs unresolved voids per department
- Add anomaly badge display when matched > reported
- Add discounts/promotions display as tracked: false coverage gaps
- Add export functionality for sales report reconciliation CSV
- Ensure UI is professional and follows existing design patterns

**Achieved:**
- Added reconciliationLoading, reconciliationError, and reconciliationData state variables
- Added fetchSalesReportReconciliation() function to call `/api/sales-reports/reconcile`
- Updated useEffect to fetch reconciliation data when ticket/docket data updates
- Implemented complete Sales Report Aggregate Reconciliation UI (Screen 6) with:
  - Loading and error states
  - Pair tally summary showing total void items, matched, needs review, unmatched
  - Per-department reconciliation table showing:
    * Voids: reported, matched, unresolved, anomaly flag when matched > reported
    * Discounts: reported count with "tracked: false" coverage gap note
    * Promotions: reported count with "tracked: false" coverage gap note  
    * Cancelled: count and amount for reference
  - Coverage information section explaining tracking status
  - Refresh button to recalculate reconciliation
  - Export button to download sales report CSV
- Added necessary CSS styles for reconciliation UI components
- Verified backend API endpoints are functioning correctly:
  * POST /api/upload/sales-reports (sales report upload)
  * GET /api/sales-reports/reconcile (aggregate reconciliation)
  * GET /api/sales-reports/export (CSV export)
- UI follows existing design patterns and is consistent with other upload sections

**Planned changes:**
- New document type: till Work Period Report (Z/X report) — the ground-truth
  aggregate table per department (Voids/Discounts/Promotions/Cancelled totals,
  each with count + amount). This is Division 6 reference data for the
  Division 5c void tally: `reported vs matched vs unresolved`.
- Upload: operator selects a restaurant, then uploads a sales report as an
  image and/or a CSV export. New `POST /api/upload/sales-reports` with
  optional image (`file`) and optional CSV (`csv_file`); at least one
  required. Store against `restaurant` + report `date` (the same-day scope
  used by ticket/docket matching).
- Image/CSV cross-verification: when both are provided, parse both and compare
  the key department totals (voids count/amount, discounts count/amount,
  promotions count/amount, cancelled count/amount). On disagreement do NOT
  store — return a mismatch report and require the operator to confirm which
  source wins before storing.
- Extraction: vision-first (reuse `app/extraction/vision.py`) with Tesseract
  OCR+regex fallback when no Gemini key is configured; CSV parsing module that
  stays flexible until the real till export structure is confirmed with the
  user (do not assume CSV mirrors the image layout).
- New `sales_reports` SQLite table keyed by restaurant + date, storing
  department-level aggregates (voids/discounts/promotions/cancelled totals),
  `extra_fields` for unrecognized lines, source, extraction method, raw text,
  and cross-verification state.
- Aggregate reconciliation layer, additive on top of the existing per-pair
  tally: for each restaurant/date/department report the figure "X voids
  recorded — Y matched — Z unresolved". Matched comes from the existing
  per-pair `build_void_reconciliation()` grouped by restaurant/date/department.
  If matched exceeds reported, surface an anomaly instead of silently ignoring.
  Discounts/promotions are ONLY compared when the system already tracks them
  per-pair — per mvp_spec they currently do NOT (only voids do), so the
  discounts/promotions comparison is surfaced as a coverage gap, never faked.
- Docs: mvp_spec (sales report schema + aggregate layer), architecture
  (module locations), frontend_spec (sales report upload screen + where the
  aggregate figure displays), decisions (image/CSV cross-verification approach
  + discounts/promotions gap), CONTEXT.md status. No automated tests.

**Awaiting from user before finalizing CSV parser + acceptance run:**
- Real sales report sample image
- Real CSV export of the same report (if the till can export one)
- Restaurant name(s) + report date for the sample, and optionally the
  GEMINI_API_KEY file at /tmp/opencode/gemini.env to enable vision + close
  out Session 23.

**Achieved (code built and verified on a synthetic report; real-sample
acceptance pending user samples):**
- `app/models/sales_report.py`: `parse_sales_report_text` (date via
  labeled/any-date regex, restaurant via labeled scan then best corporate-
  hint line, department sections via `Incomes`/`Dept` markers with the
  generic alphabetic branch gated until the report header block passes,
  totals via `Voids/Discounts/Promotions/Cancelled Total` with `-` parsed
  as zero, unrecognized lines to `extra_fields`), `parse_sales_report_csv`
  (Layout A wide header mapping, Layout B printed-mirror fallback;
  documented TOLERANT/UNVERIFIED until a real till export is seen), and
  `compare_reports` (counts exact, amounts within 0.005).
- Fixed a shared-mutable default bug found during testing:
  `REPORT_SCHEMA.departments` was append-accumulating across calls because
  `dict(REPORT_SCHEMA)` shallow-copies the list; replaced with a fresh list
  per parse.
- `app/storage/db.py`: `sales_reports` table (restaurant, report_date,
  departments JSON, source, cross_verified, confirmed_source,
  image_filename, csv_filename, extracted_text, extraction_method,
  extra_fields, timestamps), `upsert_sales_report` (ONE row per
  restaurant+date; re-upload replaces — verified no accumulation),
  `get_sales_reports`, `get_sales_report_by_id`.
- `app/api/upload.py`: `POST /api/upload/sales-reports` with optional
  `file` (image) and/or `csv_file`, optional `restaurant` override, optional
  `confirm` ("image"|"csv"). Vision-first with Tesseract+FALLBACK; image+CSV
  cross-verification returns a structured 409 `{status: "mismatch", ...}`
  without storing; re-uploads replace; read-back verification before success.
  Files are stored under `data/uploads/sales_reports/` and cleaned up on
  failure paths.
- Aggregate reconciliation: `app/api/sales_report_reconciliation.py`
  `GET /api/sales-reports/reconcile` computing per restaurant/date/department
  `{reported, matched, unresolved, anomaly}` for voids (matched from the
  existing per-pair `build_void_reconciliation()` grouped by department) and
  discounts/promotions surfaced as `tracked: false` coverage gaps. Added
  `department` to the void-reconciliation `_ticket_payload` for grouping.
- Read/export: `GET /api/sales-reports` and
  `GET /api/sales-reports/export` in `app/api/records.py`; router registered
  in `app/main.py`.
- Verified: all modules `py_compile` clean; a synthetic Z-report (TAKE AWAY
  `Voids Total: 1 15.98`, RESTAURANT `Voids Total: 6 52.42`, dash values,
  both CSV layouts) passes text/OCR/cross-verify/reconcile checks; the
  upload endpoint sequence (image-only, image+csv cross-verified, mismatch
  409, confirm=csv, csv-only, missing-files 400) leaves exactly ONE row per
  restaurant+date. Test data was removed from the DB afterwards.
- Docs updated in-session: `decisions.md`, `MVP_spec.md`, `architecture.md`,
  `frontend_spec.md`, `context.md`.
- Pending user input: real report image, real CSV export, restaurant/date,
  and `GEMINI_API_KEY` for the vision acceptance run.
- **This session**: Frontend sales report (Work Period Report) upload UI built
  per `frontend_spec.md` Screen 5: restaurant selector, image + CSV upload
  controls, cross-verification mismatch handling (409 → choose image/csv), and
  display of stored report details (restaurant, date, source, extraction method,
  cross-verified state, per-department totals). `POST /api/upload/sales-reports`
  integration with form data (`file`, `csv_file`, `restaurant`, `confirm`).
  Upload status items visible in UI. Compatible with backend on synthetic and
  real report samples.

## Session 21 — 2026-09-22
**Planned changes:**
- Add status column to tickets and dockets tables in the parsed records view
- Implement visual styling for entries with status "needs_description" (distinct styling)
- Add description prompt/modal for updating descriptions on entries that need them
- Wire up description updates via PATCH /entries/{id} endpoint using existing updateEntry function
- Import and use entries.js updateEntry function in App.jsx
- Ensure all implementations match frontend_spec.md exactly
- Flag any endpoint shape mismatches with frontend_spec.md (don't silently work around)
**Achieved:**
- Added status column to both tickets and dockets tables with proper styling for each status type
- Implemented distinct visual styling for entries with status "needs_description" (light yellow background)
- Added description prompt/modal that opens when clicking on entries with "needs_description" status
- Wired up description updates using the existing updateEntry function from entries.js
- Imported updateEntry from './api/entries' and used it to save description changes
- Verified all endpoint usage matches frontend_spec.md exactly:
  - GET /tickets and GET /dockets for data retrieval
  - PATCH /entries/{id} for description updates
  - POST /upload/tickets and POST /upload/dockets for uploads (unchanged)
- No endpoint mismatches found - all implementations follow the spec precisely
- Added comprehensive CSS styling for new elements including status cells, row highlighting, and modal UI
- Enhanced table row interaction: clicking on "needs_description" entries opens description prompt, other entries proceed to ticket comparison view
- **Added keyboard navigation support: pressing Enter on "needs_description" entries opens description prompt, pressing Enter on other tickets opens ticket comparison view**
- Properly handled keyboard navigation (Enter key) for both table interactions and modal controls
- Implemented proper modal backdrop closing and escape handling
- Added loading states and error handling for description save operations
- After successful description save, automatically refreshes the relevant data table (tickets or dockets)
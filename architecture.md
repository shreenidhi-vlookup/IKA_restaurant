# ARCHITECTURE.md — TIL SYSTEM

## 1. High-level split
Backend (this repo) and frontend (teammate's repo) are separate. Backend
exposes a REST API; frontend consumes it per `frontend_spec.md`.

## 2. Backend responsibilities (FastAPI)
- Receive single or bulk image uploads
- Receive bulk ticket screenshots and merge them into ticket records by Ticket ID
- Receive bulk discrepancy dockets and preserve printed OCR separately from handwriting
- Run text extraction on images (OCR with preprocessing + OSD deskew)
- Parse ticket screenshots and docket images into separate fixed field sets;
  missing values are null and unknown labels go to `extra_fields`
- Segment the text into blocks (header / metadata / line items / discrepancy
  markers / totals / payment) and bind each marker to its line item
- Persist rows (including the structured `blocks` JSON)
- Reconcile ticket records against image entries using ticket number as the
  primary match key and restaurant + date + amount as a fallback only when
  the numbers are absent or incomparable
- Capture handwritten reasons as a separate field and assess whether the note
  plausibly addresses the discrepancy with explicit operator-review evidence
- Serve the table data to the frontend
- Generate CSV export
- Ingest the two sales-report sources (the long slip image and the Excel Daily
  Exception Report), cross-verify them, and store one row per branch + working
  day (Division 6 ground truth)
- Reconcile aggregate report figures against the per-pair void tally
  (reported vs matched vs unresolved, per department)

## 3. Proposed directory structure

    til-system-backend/
    ├── context.md
    ├── MVP_spec.md
    ├── architecture.md
    ├── frontend_spec.md
    ├── rules.md
    ├── decisions.md
    ├── session_log.md
    ├── app/
    │   ├── main.py                # FastAPI app entrypoint
    │   ├── api/
    │   │   ├── upload.py          # POST endpoint: receive image(s)
    │   │   ├── entries.py         # GET/PATCH endpoints: table rows
    │   │   ├── export.py          # GET endpoint: CSV export
    │   │   ├── void_reconciliation.py   # per-pair void tally (5c)
    │   │   ├── sales_report_reconciliation.py  # aggregate report vs tally + Process dashboard
    │   │   └── records.py         # ticket/docket/sales-report reads + CSVs
    │   ├── extraction/
    │   │   ├── ocr.py             # text extraction from image (preprocess + OSD deskew + Tesseract)
    │   │   └── vision.py          # vision-first Gemini extraction (optional, stdlib-only)
    │   ├── models/
    │   │   ├── entry.py           # data model for a bill/discrepancy row
    │   │   ├── segmentation.py    # block segmentation + auditable value correction
    │   │   └── sales_report.py    # long-slip parsing, shared xlsx reader, canonical dates
    │   ├── daily_exception.py # Excel Daily Exception Report row-level parsing
    │   ├── storage/
    │   │   └── db.py              # persistence layer (SQLite for MVP)
    │   └── core/
    │       └── config.py
    ├── data/
    │   └── uploads/                # stored images
    └── requirements.txt

## 4. Data flow

    [image upload] -> [FastAPI /upload or /upload/bulk] -> [OCR extraction (preprocess + Tesseract)]
        -> [parse_extracted_text (fields + blocks/segment_text)]
        -> [determine_status (precedence; low-confidence marker -> needs_review)]
        -> [structured row + blocks JSON stored in DB]
        -> [/entries returns table data] -> [frontend renders table]
        -> [/export returns CSV of current table/filtered view]

      Bulk image uploads are processed synchronously, one image at a time through
      the same extraction/parsing/persistence pipeline as `/upload`. The bulk route
      accepts up to 30 images and isolates exceptions per image, returning stored
      successes alongside filename/reason failures. No background job or polling is
      required for the current MVP contract; the frontend can refresh `/entries`
      after the request completes.

      Ticket screenshot batches use `/api/upload/tickets`, OCR each screenshot,
      normalize its Ticket ID, and upsert one SQLite `ticket_records` row. The
      row stores flexible ticket fields, `extra_fields`, deduplicated item rows,
      raw OCR text, and screenshot filenames. Screenshots are saved under
      `data/uploads/ticket_screenshots/`; item merge keys are normalized item
      name + quantity + unit price, and void rows retain `is_void: true`.
      The generic `/api/upload` and `/api/upload/bulk` paths inspect OCR before
      accepting an image; a full Ticket ID plus ticket-screen labels is routed
      into `ticket_records` and `ticket_screenshots` instead of `entries`.
      Unrecognized non-ticket images are rejected from the generic path and
      must use the dedicated docket endpoint. Ticket IDs remain one
      hyphenated string such as `260920-143`.

      Docket batches use `/api/upload/dockets`, save images under
      `data/uploads/dockets/`, and create one `docket_records` row per image.
      The parser stores `docket_order_no` as a weak trailing-order key, docket
      date/time, item, printed discrepancy type, separate `handwritten_reason`,
      printed/raw OCR, and review flags. Multiple detected order numbers cause
      manual review; the endpoint never invents a full Ticket ID.

      Void reconciliation reads `ticket_records.items` where `is_void` is true
      and matches each item to `docket_records.docket_order_no` using the
      trailing Ticket ID digits. A unique date match resolves a collision;
      unresolved collisions retain every candidate and become `needs_review`.
      The builder sorts `matched`, then `needs_review`, then `unmatched`, adds
      `row_position`, and is shared by both the JSON and CSV endpoints.

      `/api/tickets` returns one merged ticket row with prominent `ticket_id`,
      `uploaded_at` (latest screenshot upload/merge time), and its
      normalized `items[]` from the `ticket_items` child table. The frontend
      keeps the dataset collapsed until Show data and renders an expandable
      item sub-table. `/api/dockets` returns order_number, date, time, item,
      discrepancy_type, and description. Upload success is
      returned only after the inserted row is read back from its dedicated
      table.

      The generic entries dataset is not used by ticket/docket ingestion or
      the active UI. The two dedicated datasets are the only parsed record
      tables shown to operators.

      Sales reports (Division 6) use `/api/upload/sales-reports` with two
      independent sources, either or both, scoped to one branch + working day:

      - **Source 1, the long slip** (multipart `file`): a photo of the till's
        printed Work Period Report. Vision-first via `app/extraction/vision.py`
        with Tesseract OCR + `parse_sales_report_text` as the fallback
        (`extraction_method` recorded, never hidden). The default Gemini model
        is `gemini-3.8-flash`; `gemini-2.5-flash` returns HTTP 404. `-` in a
        total is zero, not missing.
      - **Source 2, the Excel Daily Exception Report** (multipart `excel_file`):
        a row-level `.xlsx` log parsed by
        `app/models/daily_exception.py` (raw zipped-XML sheet reader, no
        dependency). `Daily Void Log` is preferred; `Daily Exception Summary` is
        a void-amount sanity check only. `Adjustment Type` starting with `Void`
        is a void, a **blank** one is `unfilled` and is never a void. Bill
        numbers have whitespace removed, rows are counted and never deduplicated
        by bill, and a row's day comes from its bill number's `YYMMDD` prefix.
        Rows outside the selected branch/day are skipped and the skipped count
        is reported.

      `compare_slip_with_excel` cross-verifies the **void amount** for the
      branch + day; the void **count** comparison is returned but explicitly
      unscored, because it is not yet confirmed whether the slip counts voided
      items or voided bills. A disagreement returns a structured 409 and stores
      NOTHING until the operator re-submits with `confirm=slip|excel`; the chosen
      source lands in `confirmed_source` and `cross_verified` stays false.

      The working day is the operator's selection, required, and is never taken
      from the slip's printed date. For tickets the day is the Ticket ID's
      `YYMMDD` prefix (the printed date is a fallback), because a till can print
      a date that differs from the day the report is filed under. All layers
      share one `canonical_date_key` in `app/models/sales_report.py` so a day
      written two ways still joins.

      Reports persist ONE row per branch + day in `sales_reports`
      (`upsert_sales_report` replaces), with the parsed Excel rows in the
      `daily_exception_rows` child table, also replaced wholesale. Uploaded
      source files live under `data/uploads/sales_reports/`.

      `GET /api/sales-reports/reconcile` builds the aggregate layer on the
      per-pair void tally: `build_void_reconciliation()` rows are grouped by
      restaurant / date / department (the pair builder exposes `department`
      on each ticket payload) and matched against the report's department
      totals, producing reported / matched / unresolved plus an anomaly flag
      when matched exceeds reported. Discounts/promotions are reported but
      surfaced as untracked coverage gaps.

      `POST /api/sales-reports/process` is the Process button's only data
      source. `build_process_dashboard` recomputes every dashboard figure per
      run for one branch + day: the report scope, the Bill-vs-Excel check, the
      ticket void-item count, dockets filed that day, matched / needs-review /
      unresolved voids, the unmatched ticket voids and unmatched dockets as
      LISTS, per-department and total figures, an anomaly flag when matched
      exceeds reported, discounts/promotions marked not yet reconciled, and a
      `missing` list naming absent inputs. Dockets carry no restaurant column,
      so docket figures are date-scoped only and the payload says so. Because a
      docket is paired on its trailing order number, a matched docket may carry
      a printed date other than the working day, so dockets filed on the day and
      dockets used in matches are reported as separate figures.

      `GET /api/restaurants` returns Ilford, Southall and Norbury — always all
      three, including branches with no tickets yet — each with the till
      `restaurant_names` behind it, so the frontend never hardcodes branches or
      maps restaurant names itself.

## 5. Division-to-code mapping
| Division | Code location |
|---|---|
| 1. Image input + extraction | `app/api/upload.py`, `app/extraction/ocr.py` |
| 2. Table / discrepancy data | `app/models/entry.py`, `app/api/entries.py`, `app/storage/db.py` |
| 3. CSV export | `app/api/export.py` |
| 4c. Ticket reconciliation | `app/models/reconciliation.py`, `app/api/reconciliation.py` |
| Ticket screenshot input | `app/models/ticket.py`, `app/api/upload.py`, `app/storage/db.py` |
| Docket input | `app/models/docket.py`, `app/api/upload.py`, `app/storage/db.py` |
| Void reconciliation | `app/api/void_reconciliation.py`, `app/storage/db.py` |
| Parsed ticket/docket reads and CSVs | `app/api/records.py`, `app/storage/db.py` |
| Long-slip parsing, shared xlsx reader, canonical dates | `app/models/sales_report.py` |
| Excel Daily Exception Report parsing | `app/models/daily_exception.py` |
| Sales report upload + cross-verification | `app/api/upload.py`, `app/extraction/vision.py`, `app/storage/db.py` |
| Process dashboard (backend owns every figure) | `app/api/sales_report_reconciliation.py` |
| Aggregate sales-report reconciliation | `app/api/sales_report_reconciliation.py`, `app/api/void_reconciliation.py` |

## 6. Open decisions (resolve and move into decisions.md)
- How ticket number / restaurant are identified from extracted text
  (regex? fixed template per restaurant? manual entry fallback?)

## 7. Resolved decisions
- OCR engine/service choice: Selected Tesseract OCR (recorded in decisions.md)
- Storage layer: Selected SQLite for MVP (simple, file-based, sufficient)
- Text parsing approach: Selected regex/keyword matching (extract ticket # and discrepancy type)
- CSV export functionality: Selected GET /export endpoint with filtering support (restaurant, ticket_number)
- CSV image representation: Selected to export stored image filename/path instead of thumbnail
- Entry model: Added extra_fields (dict) for capturing unexpected bill fields, image_filename for CSV export reference
- Status values: Expanded to matched, needs_description, needs_ticket_number, needs_restaurant, needs_discrepancy_type, needs_review
- Parsing strategy: Retained regex/rule-based over LLM; multiple patterns with graceful degradation for schema flexibility
- OCR preprocessing: grayscale -> 2x LANCZOS upscale (<1400px) -> autocontrast(cutoff=1) -> OSD deskew (rotate only at confidence >= 5.0); Tesseract `--oem 3 --psm 6`
- Block segmentation: `app/models/segmentation.py` splits the OCR blob into header / metadata / line_items / discrepancies / totals / payment; every value fix is recorded in `corrections` (auditable)
- Discrepancy association: marker binds to nearest preceding item; high confidence iff gap <= 2 lines and marker amount matches line_total; otherwise low -> status `needs_review`
- `blocks` column: additive `blocks` JSON column on entries (deserialized by `entries.py`); raw `extracted_text` kept for audit; `/upload` response `parsed_data` stays at the original 5 fields
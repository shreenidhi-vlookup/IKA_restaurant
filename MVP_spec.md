# MVP spec — CSV-driven discrepancy verification

## Purpose
Operators compare a till item CSV for one restaurant branch and business date with POS ticket screenshots and printed discrepancy dockets. Backend extraction and matching are authoritative.

## Workflow
1. Select branch (Haweli Restaurant Southall, Haweli Restaurant Norbury, or Haweli Ilford Ltd) and date.
2. Upload one CSV. The parser finds the header containing **Product Name**, skips blank lines, handles CRLF, and stores every row under branch/date. The first-line totals are informational only. A mismatching row date requires an explicit confirmation.
3. Show five horizontal boxes: Total (row count and quantity), Void, Cancel, Promotions, Status. Flag columns use their numeric values. Promotion is **Not in file** when no promotion/discount column exists; Gift is not a promotion.
4. Clicking a discrepancy box shows matching CSV rows and Pending, Partial, Verified, or Needs review status. Clicking a verified row shows the CSV row beside exact ticket and docket fields and image thumbnails. Missing handwriting is shown as **No description**, without downgrading Verified.
5. Upload batches of up to 30 ticket screenshots or dockets. Local Tesseract OCR parses ticket screenshots; Gemini vision extracts printed and handwritten docket data. Saved files automatically trigger backend reconciliation and UI refresh. Batch failures are reported by filename.

## Parsing and verification
- Ticket identity keeps its complete YYMMDD-N string. The date for matching comes from its YYMMDD prefix. Ticket fields/line items are merged by ID; filled values survive blank screenshots and only new items append. Item overlap uses name, price, quantity, total, modifier, and void state, preserving legitimate repeated names.
- Ticket scalar fields map to `ticket_records`: `ticket_id`, `restaurant`, `ticket_date`, `terminal`, `table_name`, `department`, `user_name`, `payment_status`, `credit_card_amount`, `ticket_total`, `grand_total`, and `charged`. `ticket_items` stores each ordered row as `item`, `modifier`, `category`, `price`, `qty`, `total`, and `is_void`, with `row_tint`, `strikethrough_line`, `void_label_text`, `void_confidence`, and `review_flags` saved alongside it.
- Ticket-to-CSV matching requires same day, case-insensitive user, department, terminal/till, normalized product, quantity, and value. Strip trailing (Void) and price modifier lines. Missing/conflicting/non-exact fields are never auto-verified.
- Each image batch is associated with the selected branch. Docket order number equals the full trailing ticket ID digits exactly. Docket item and staff must agree. Multiple candidates remain Needs review.
- Flag count and quantity determine required pair count. Show partial counts when fewer matched pairs exist.
- Docket description is handwritten text only; absent handwriting is null. Preserve confidence, image review flag, extra fields, and raw Gemini JSON by file. Ticket OCR retains both the original recognized text and the line-cleaned pass in its per-file audit.

## API
- POST /api/csv multipart branch, selected_date, file, optional confirm_date_mismatch.
- GET /api/verification?branch=…&selected_date=… provides rows, statuses, candidates, and box summary.
- GET /api/verification/dates?branch=… lists saved CSV dates with source filename and row counts; the operator can open a prior date's discrepancy rows.
- POST /api/upload/tickets and /api/upload/dockets accept files batches and branch/date form fields.
- GET /api/uploads?branch=?&selected_date=? lists saved upload images; DELETE /api/uploads/{ticket|docket}/{filename} removes one image and its linked extraction records.
- GET /api/images/{ticket_screenshots|dockets}/{filename} serves evidence image previews.

## Stack and setup
FastAPI, React/Vite, PostgreSQL (or SQLite when DATABASE_URL is unset), local Tesseract OCR for ticket screenshots, and Gemini vision for docket photos. Set GEMINI_API_KEY and GEMINI_MODEL in the project-root .env file; app startup loads them through python-dotenv. Ticket OCR uses the pytesseract Python wrapper plus the separate Tesseract OCR 5 executable. Install Python dependencies on the operator's machine with `python -m pip install -r requirements.txt`; install the Windows Tesseract engine separately and make it available on PATH or configure TESSERACT_CMD. Previous CSV imports remain browsable by branch/date. No test suite is part of this MVP; acceptance is manual.

## Ticket and docket evidence rules
- Ticket IDs must match `^\d{6}-\d+$`. Unreadable IDs and branch/day mismatches stay in an unassigned queue until the operator enters an ID and explicitly confirms mismatches.
- Exact image bytes are keyed by SHA-256 per upload type only while queued/processing or after saved extraction. Repeats with an existing saved image report `duplicate, skipped`; extraction failures retain the source image and job error for retry or operator handling. Ticket screenshots are EXIF-corrected and passed to local Tesseract `image_to_data` for positioned OCR. The OCR path repairs long horizontal strokes inside detected item-table rows for a corroborating pass, while original pixels supply row tint and strikethrough signals. The repaired pass may confirm a literal `(Void)` suffix but cannot override item names or amounts from the original pass. A row is void when its relative pink tint or strikethrough signal fires; strikethrough without tint is marked low confidence for review. Each item stores `modifier`, `row_tint`, `strikethrough_line`, `void_label_text`, `void_confidence`, and review flags. Both OCR text passes and the parsed structured ticket are audited per file. Docket images go to Gemini vision for structured extraction, including handwriting.
- Ticket screenshots with the same ID merge filled info fields and ordered item segments. Only matching end/start item runs are overlap-dropped; repeated lines within a segment remain. Unorderable segments set `possible gap: a screenshot may be missing`; conflicting totals and item-total discrepancies are review flags.
- Dockets merge by branch/date/order/time and compatible void-item sets. Complementary item views and every source image are retained; conflicting readings and cropped fields are shown for review. Same order with different time or distinct void items remains separate. Unmarked lines remain normal items.
- Matching is backend-only. Ticket-to-CSV requires exact normalized identity and amount/quantity fields; docket-to-ticket requires exact trailing order digits plus item, staff, department, and day. Each verified pair contributes only the supported quantity. Ambiguity or conflicts require review; ticket-only and docket-only evidence is Partial.
- GET `/api/tickets/unassigned` and POST `/api/tickets/resolve` list and assign held screenshots. GET `/api/uploads` lists images for the selected branch/day; DELETE `/api/uploads/{kind}/{filename}` deletes one photo and its associated extracted evidence.

## Structured extraction schemas
Ticket OCR output and Gemini docket output are validated against strict Pydantic extraction models. Gemini receives the docket JSON schema and its response is validated locally against the same strict model.

## Extraction queue and fallback
- Image uploads are persisted as per-file jobs and return immediately with a batch ID. Jobs progress through `queued`, `processing`, `done`, or `failed`; the frontend polls `/api/upload/jobs/{batch_id}`.
- A shared process-local request pacer uses `EXTRACTION_MAX_RPM` (default 4) across Gemini docket calls and retries. Local ticket OCR does not consume provider RPM. `EXTRACTION_CONCURRENCY` (default 2, supported 1-8) controls worker count. Set these according to the Gemini project quota.
- The request pacer is process-local; deployments with multiple API worker processes must keep extraction on one process or add a shared limiter before scaling across processes.
- Gemini vision is active only for docket extraction (`GEMINI_MODEL`, default `gemini-3.5-flash-lite`, key in `GEMINI_API_KEY`). NVIDIA is not used by the upload workflow. Ticket screenshot OCR uses Tesseract and is audited per file; Gemini output is validated locally against the strict Pydantic docket schema.

## Local Ethernet preview
The Vite development server binds to 0.0.0.0 on port 5173 by default, with a strict fixed port. Open http://<host-ethernet-ip>:5173/ from a device on the same subnet. Vite proxies /api requests to the local FastAPI service on 127.0.0.1:8000, so only port 5173 needs an inbound firewall rule.


Ticket OCR tries multiple Tesseract page-segmentation layouts and combines missing fields from alternate passes. When a WhatsApp screenshot crops the item-table heading, the parser detects rows from their POS price/quantity/total column positions, preserves wrapped item names, and re-reads tinted/struck rows for their item text. Metadata not present in the screenshot remains blank rather than being guessed from unrelated text.

- Before extraction, a single fast local Tesseract pass classifies structural ticket/docket markers. A confident mismatch is returned as that file's failed job with a clear type-specific message; uncertain images are held as failed-for-review jobs. Neither case reaches extraction or record storage. The staged image is retained and each rejection is audited with filename, reason, and timestamp. Other batch files continue independently.


Evidence image responses use `Cache-Control: public, max-age=31536000, immutable` because stored names are immutable UUIDs. A scheduled hourly sweep removes successfully resolved source images after 24 hours from the upload job timestamp (UTC), never from the selected business date. Failed jobs, unassigned screenshots, records requiring review, and records with no extracted ticket/docket items are exempt until resolved. Every automatic deletion is recorded in `upload_audits`.

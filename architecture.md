# Architecture — CSV verification

FastAPI owns import, extraction, persistence, and all matching. React selects branch/date (Haweli Restaurant Southall, Haweli Restaurant Norbury, or Haweli Ilford Ltd), uploads the CSV and image batches, renders API statuses, and requests refresh after successful uploads. The frontend never performs matching.

## Backend modules
- app/api/verification.py: CRLF-safe CSV import, branch/date row storage, date confirmation, summary, and backend match builder.
- GET /api/verification/dates lists imported dates and discrepancy-row counts for the selected branch so prior records can be opened by date.
- app/api/image_upload.py: per-file ticket/docket batches and partial failure reports.
- app/extraction/ticket_ocr.py: local Tesseract OCR parses ticket screenshot text and line-cleans the item table for a second pass while preserving void cues from original pixels. app/extraction/gemini.py sends docket images to Gemini vision for structured printed and handwritten extraction. app/main.py loads the project-root .env through python-dotenv; GEMINI_API_KEY is required for docket vision.
- app/storage/db.py: CSV rows, merged tickets/items, dockets, and per-file extraction audit JSON. `DATABASE_URL=postgresql://...` in .env selects PostgreSQL (psycopg 3); without it the local SQLite file data/til_system.db is used. SQL is written once in a form both accept (`?` placeholders are translated for Postgres, upserts use `ON CONFLICT`, inserts use `RETURNING id`). Timestamps stay UTC `YYYY-MM-DD HH:MM:SS` text and JSON columns stay text on both, so API output is identical. Ticket and docket read-modify-write saves take a per-record lock (`BEGIN IMMEDIATE` on SQLite, `pg_advisory_xact_lock` on Postgres) so parallel extraction workers cannot overwrite each other.
- scripts/migrate_sqlite_to_postgres.py: one-transaction copy of the SQLite file into Postgres, followed by per-table row-count and content-fingerprint verification (`--verify` to re-check only).
- tests/: pytest suite (`python -m pytest`); set TEST_DATABASE_URL to a database whose name contains `test` to run it against Postgres.
- app/main.py: API routes and evidence-image static paths.

## Storage and matching
Every imported CSV line is stored in csv_rows keyed by branch and selected date; reimport replaces that branch/date dataset. Image batches retain both extracted branch metadata and their selected-branch association. `/api/uploads` lists saved image files by selected branch/day; delete removes that image, its hash/audit/jobs, and associated or merged evidence. ticket_records and docket_records retain structured model output; upload_audits keeps raw JSON for each extraction. Matching derives statuses from saved rows and is rebuilt after image uploads and on verification reads. Ticket day is the ID prefix. Exact values and normalized strings gate ticket candidates. Docket order number is compared as an entire trailing ID segment; item/staff disagreement and multiple candidates surface as Needs review. A row needs enough ticket+docket pairs to cover its flagged count/quantity to become Verified.

## Data flow
CSV -> /api/csv -> csv_rows -> /api/verification -> five boxes/details

ticket image -> local Tesseract OCR -> ticket record + text audit -> automatic verification rebuild -> UI refresh
docket image -> Gemini vision JSON -> docket record + raw response audit -> automatic verification rebuild -> UI refresh

No slip upload, Excel parser, client Process action, generic bill pipeline, or old reconciliation pipeline remains in the MVP.

## Evidence merge and review details
Ticket screenshots are deduplicated by SHA-256 and merged by full ticket ID. Visible item sequences are joined only across matching suffix/prefix overlap; non-orderable fragments carry a possible-gap review flag. Conflicting repeated totals and non-void item-sum discrepancies appear as ticket review flags. Invalid IDs or branch/day mismatches are held for operator assignment/confirmation.

Docket records retain all image filenames, item lines, and complementary views. Candidate dockets with the same branch/date/order/time and compatible marked-item sets merge; contradictory field readings remain in field_conflicts and set Needs review. Distinct marked items or times remain separate docket records. Gemini raw JSON is stored in upload_audits per docket file; preprocessing applies EXIF orientation, bounded resize, and contrast/brightness adjustment, with one retry after strict schema validation failure. Ticket screenshots use local Tesseract `image_to_data` OCR so item rows retain bounding boxes. The original pass supplies mapped fields and item order; horizontal-stroke repair produces a corroborating pass for a literal `(Void)` suffix. Original pixels estimate each row background from bright pixels and compare its red excess with the adjacent row, avoiding a fixed RGB target. A row is void when tint or strikethrough fires; strikethrough without tint receives a low-confidence review flag. Item modifiers stay attached to their row, and all three signals are stored per item for review.

The Gemini JSON schema is sanitized to omit unsupported `additionalProperties` and `default` keywords. At startup, previously failed provider-less docket jobs are requeued once through the active Gemini path; failures record the provider to prevent restart loops. Docket views from the same image and order merge as complementary views.

Gemini docket extraction uses structured JSON at temperature zero and retries transient 429/503 errors with provider delay guidance. Ticket OCR is local and does not use provider retries.

## Background extraction
POST upload endpoints stage each image for extraction and create a persisted `extraction_jobs` row, then return a `batch_id`; failed extraction retains the staged image and hash with its per-file failure reason; startup resumes queued or interrupted jobs. Configured workers invoke extraction off the event loop. Ticket jobs run local Tesseract OCR and do not consume provider RPM. Docket jobs call Gemini; a process-local monotonic request pacer spaces every request and retry according to `EXTRACTION_MAX_RPM`. Worker count comes from `EXTRACTION_CONCURRENCY`. Docket raw Gemini responses are audited and validated against the strict Pydantic schema before storage. Ticket original/cleaned OCR text and structured results are audited per file. `/api/upload/jobs/{batch_id}` exposes per-file progress and errors. `/api/uploads` lists saved images for the selected branch/day, and DELETE removes the selected image plus its extraction references. Summary/detail copy actions write formatted plain text for pasting into Word. Multi-process deployments need a distributed limiter for a provider-wide RPM guarantee.

Install the Tesseract 5 Windows engine and the Python dependencies in `requirements.txt`; the app searches PATH and the standard `C:\Program Files\Tesseract-OCR\tesseract.exe` location. Set `TESSERACT_CMD` to the executable path if installed elsewhere. Docket extraction uses `GEMINI_MODEL=gemini-3.5-flash-lite` and `GEMINI_API_KEY`. NVIDIA is not used by either upload path.


Ticket item segment overlap fingerprints include name, price, quantity, total, modifier, and void state. Reprocessing the same screenshot replaces that source segment before running the existing overlap merge; repeated rows within one screenshot remain intact.

## Local network preview
Vite serves the frontend on all host interfaces at port 5173 and proxies /api to FastAPI at 127.0.0.1:8000. Keep the API loopback-bound; the LAN client uses the Vite origin. Allow inbound TCP 5173 from the local subnet in the host firewall.


Ticket OCR runs Tesseract page modes 6, 4, and 11 and selects/merges the richest structured parse. It falls back to label-anchored plain-text fields and headerless POS-column geometry for cropped WhatsApp ticket details; tinted/struck rows receive a dedicated multiline OCR crop pass. Absent fields are not inferred from branch or item text.

Before either image parser runs, `image_upload.py` calls `ticket_ocr.classify_document`: one inexpensive Tesseract PSM 6 pass checks for a labeled YYMMDD-N ticket ID with POS headers or printed docket receipt fields. Confident cross-type files and uncertain files become per-file failed/held jobs before extraction or record writes. Their image remains available from the uploads list, and `upload_audits` records original filename, expected/detected type, reason, and database timestamp. The worker catches each rejection independently, so other batch jobs continue.


Image lifecycle and retention live in `app/api/image_upload.py`: extraction failures keep their source image; the hourly sweep keys age from `extraction_jobs.created_at` (the upload timestamp) and deletes resolved images after a rolling 24 hours. Failed jobs, unassigned screenshots, and ticket/docket records carrying review flags or no extracted items are exempt, as are active jobs. Automatic deletion events include filename, upload timestamp, and deletion timestamp in `upload_audits`. `app/main.py` adds immutable one-year `Cache-Control` headers to successful evidence image responses.

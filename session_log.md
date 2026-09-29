# SESSION_LOG.md

> that's what lets a brand-new session (with zero memory) understand exactly
> where things left off, just by reading CONTEXT.md -> this file.
---
## Session 26 â€” 2026-09-25
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
## Session 27 — 2026-09-28
**Planned changes:**
- Replace the sales-report/Excel/slip and Process workflow with branch/date selection, CSV import, five verification boxes, and click-through CSV-row details.
- Persist all CSV rows per branch/date, validate the selected date, preserve numeric discrepancy counts, and expose promotion absence as “Not in file.”
- Add backend ticket/docket Gemini structured extraction, raw JSON audit storage, and conservative automatic CSV-to-ticket-to-docket matching after uploads.
- Remove obsolete slip/Excel/reconciliation endpoints, parsers, storage, UI, and stale docs; update decisions and all three specs.
- Do not install packages or run tests; document Gemini setup for the operator.
**Achieved:**
- Replaced the old React dashboard with branch/date selection, single CSV import, five responsive verification boxes, row detail view, and ticket/docket evidence uploads.
- Added CRLF-tolerant header-based CSV import, date mismatch confirmation, branch/date storage for every CSV row, numeric Void/Cancel/promotion counts, and explicit Not in file when promotion/discount columns are absent. Gift is not treated as Promotions.
- Added backend-owned exact-match status calculation and branch-scoped evidence association; ticket/docket uploads refresh the selected dataset and return per-file outcomes.
- Added Gemini image extraction schemas for ticket visual void signals and docket handwriting, raw model JSON audit storage, ticket merge-by-ID, docket confidence/review fields, and evidence image routes.
- Removed the generic bill upload/OCR pipeline, legacy slip/Excel/reconciliation UI and APIs, and obsolete parsers/scratch files. Cleared the old SQLite entries table; ticket/docket sample data remains.
- Replaced the stale specs and decisions with the CSV verification contract and synchronized the current status in context.md.
- Did not install packages or run automated tests. Gemini still requires operator installation/configuration and manual testing against real screenshots and dockets.

## Session 28 - 2026-09-28
**Planned changes:**
- Clear saved CSV imports and item rows so the user can begin fresh manual imports.
- Replace placeholder branch choices with the three supplied Haweli restaurant names.
- Add a date-based previous-records view for imported discrepancy data, scoped to selected branch.
- Preserve the restored DM Sans, DM Mono, and Playfair Display typography.
- Do not run tests.
**Achieved:**
- Deleted all stored csv_rows and csv_imports so the CSV workspace is empty for fresh manual imports.
- Replaced placeholder selectors with Haweli Restaurant Southall, Haweli Restaurant Norbury, and Haweli Ilford Ltd.
- Added branch-scoped date history API and View previous records UI; selecting a prior date loads its saved row details and verification summary.
- Preserved the restored DM Sans, DM Mono, and Playfair Display font set.
- Updated current project specs and branch/history decisions. No tests were run.

## Session 29 - 2026-09-28
**Planned changes:**
- Audit ticket multi-screenshot merge, overlap handling, exact duplicate detection, docket view merging/deduplication, Gemini validation/retry, automatic matching, and evidence details.
- Add per-file SHA-256 duplicate suppression and operator resolution for unassigned or mismatched ticket screenshots.
- Merge ticket screenshot fragments by sequence overlap without globally deduplicating repeated item lines; flag uncertain order, conflicting totals, and completeness discrepancies.
- Merge complementary docket views by branch/date/order/time/void-item identity while preserving conflicts, all item lines, and all image evidence.
- Harden Gemini image preprocessing, structured validation, one retry, and per-file raw JSON audit.
- Improve exact backend ticket/docket/CSV matching and show merged fields and every evidence thumbnail. Do not modify CSV parsing or summary box data.
- Do not run automated tests or install packages.

**Achieved:**
- Audit (before changes): 1 Partial, 2 Broken, 3 Missing, 4 Missing, 5 Missing, 6 Partial, 7 Partial, 8 Partial. Evidence: ticket records already upserted by ID, but item lines were globally deduplicated; no file hashes or docket merging existed; Gemini used structured schemas but lacked validation/retry; matching was incomplete and the detail view showed only one image.
- Added exact image hash suppression, held ticket screenshots for operator assignment and explicit mismatch confirmation, ticket segment overlap merge with review flags, docket multi-view merging with conflict/partial metadata and multiple-image retention.
- Hardened Gemini vision extraction with orientation/resize/contrast preparation, strict schema validation/retry, and per-file raw response audit. Added Pillow to requirements without installing it.
- Improved backend match gates and candidate display; detail cards now show every ticket/docket image and all extracted evidence, including partial candidates and conflict/no-description badges.
- Updated MVP, architecture, frontend, and decision documentation. CSV import/parser and five-box summary source were left unchanged. No automated tests or installs were run. Manual validation against the requested split screenshots, duplicate images, complementary docket views, and real Gemini responses remains outstanding.

## Session 30 - 2026-09-28
**Achieved:**
- Fixed the reported Gemini upload failure: the Developer API rejected `additionalProperties` emitted by the Pydantic schema. Extraction now sends a sanitized `response_json_schema`, while retaining strict local Pydantic validation and one retry.
- Changed `extra_fields` to typed `{label, value}` entries to avoid an open-ended object schema.
- Updated the three specs and decision log. No tests or installs were run.

**Follow-up completed:** The pasted upload log showed temporary Gemini 503 capacity errors and a free-tier 429 limit of 5 requests/minute, plus an SDK AFC warning. Image extraction now disables unused automatic function calling and retries transient 429/503 errors using the provider retry delay or exponential backoff. No provider/model was swapped: doing so would replace Gemini vision and needs an explicit provider decision. No tests or installs were run.

## Session 31 - 2026-09-28
**Planned changes:**
- Add a persisted background job queue for ticket/docket extraction, with a shared request pacer configured by EXTRACTION_MAX_RPM and EXTRACTION_CONCURRENCY.
- Preserve per-file SHA-256 duplicate handling, extraction audit, saves, and automatic verification while moving image inference off the upload response.
- Retry Gemini 429/503 responses within a bounded retry budget, honor server delay guidance, then fall back to NVIDIA vision using NVIDIA_API_KEY and NVIDIA_MODEL.
- Add per-file queued/processing/done/failed progress UI and a polling API.
- Verify the correct Gemini 3 Flash model identifier, set the project config to it, and make one explicitly requested sample extraction call if available.
- Add a safe NVIDIA API-key placeholder in .env without displaying or overwriting existing secrets; sync decisions and docs.
- Do not run automated tests or installs.


**Achieved:**
- Added a persisted background queue for ticket and docket images, with per-file `queued`, `processing`, `done`, and `failed` states exposed through a batch polling endpoint. The UI shows each filename, state, provider, and any failure message.
- Added process-wide RPM pacing configured by `EXTRACTION_MAX_RPM` and bounded worker count from `EXTRACTION_CONCURRENCY`. Gemini 429/503 errors retry up to three times using a recognized provider retry hint, then the per-file worker tries optional NVIDIA vision. Other files continue independently.
- Kept Gemini as the primary vision path and set the project `.env` model to `gemini-3-flash-preview`; configured NVIDIA model/key settings while preserving existing secret values. No key value was logged.
- Manual provider spot-check: Gemini 3 Flash returned HTTP 503 after retries. NVIDIA fallback was attempted, but its response failed local schema validation after retry. Fallback extraction has not been demonstrated to succeed and needs manual checking before reliance.
- Updated `MVP_spec.md`, `architecture.md`, `frontend_spec.md`, and `decisions.md`. `git diff --check` completed cleanly. No automated tests or installs were run; manual acceptance remains pending.


## Session 32 - 2026-09-28
**Planned changes:**
- Make NVIDIA vision the active ticket/docket extraction provider and comment out the Gemini extraction call so the operator can manually test NVIDIA.
- Keep Gemini schema/types available where shared by the NVIDIA adapter; preserve all existing API keys.
- Record the provider selection in decisions and synchronize the three specs. Do not run tests or installs.

**Achieved:**
- Switched the extraction worker to call NVIDIA directly for ticket and docket images. The Gemini inference call is commented out; its shared schema/error utilities remain imported by the NVIDIA adapter.
- Per-file NVIDIA raw response auditing, schema validation, retry behavior, and queue progress remain in place. Existing `.env` values were preserved.
- Updated MVP, architecture, frontend, and decision documentation. No tests or installs were run.


## Session 33 - 2026-09-28
**Planned changes:**
- Fix NVIDIA structured parsing when numeric JSON values are returned for text-valued extraction fields such as item quantity and price.
- Preserve strict schema validation for field shapes and types outside safe numeric-to-text normalization.
- Document the compatibility decision. Do not run tests or installs.

**Achieved:**
- The stored NVIDIA response showed valid extraction JSON with integer item quantities. Pydantic rejected those values because the application schema represents the affected fields as text.
- Added field-aware numeric-to-string normalization before schema validation, preserving strict validation for other data and keeping the raw provider response in the audit record. Validation failures now include the last schema error to aid diagnosis.
- Updated all three specs and the decision log. `git diff --check` is clean. No automated tests or installs were run.


## Session 34 - 2026-09-28
**Planned changes:**
- Replace ticket screenshot NVIDIA vision extraction with local Tesseract OCR; keep NVIDIA vision extraction for docket handwriting only.
- Preserve ticket structured fields and strikethrough/label/row-tint void signals. Use local horizontal-stroke cleanup and OCR coordinates to recover struck-through names while retaining void evidence from the original image.
- Add the Python wrapper requirement and report the separate Tesseract Windows engine requirement; do not install anything or run tests.
- Update the decision log, MVP, architecture, frontend spec, and achieved session notes.

**Achieved:**
- Ticket screenshots now use a local Tesseract OCR extractor; NVIDIA is called only for docket photos and their handwritten descriptions.
- Added a structured ticket parser for ticket ID, branch, info-card fields, item/category/price/quantity/total columns, and ticket totals. It OCRs the original screenshot, repairs long horizontal strokes within the detected item table, runs a second OCR pass, and derives void signals from the original strike-through pixels, `(Void)` label, and row tint. Both OCR transcripts and structured values are audited per file.
- Added `pytesseract` to requirements and optional `TESSERACT_CMD` configuration. This workspace has neither the Python wrapper nor the Tesseract executable, so image-level OCR could not be manually exercised. No installs or automated tests were run. AST syntax parsing and `git diff --check` passed; operator manual validation remains necessary after installing Tesseract.
- Updated decisions, MVP, architecture, frontend spec, and context documentation.

## Session 35 - 2026-09-29
**Planned changes:**
- Keep ticket extraction on local pytesseract; refine ticket field parsing, modifier attachment, void signal auditing, and item sequence overlap fingerprints using the supplied screenshots.
- Make row tint relative to adjacent rows; record `row_tint`, `strikethrough_line`, and `void_label_text`, with low-confidence review metadata when only strikethrough is detected.
- Preserve the existing ticket-ID segment merge while distinguishing legitimate repeated rows by name, price, quantity, total, and modifier.
- Rebuild verification for affected stored tickets after corrected ticket extraction; do not change docket extraction or CSV parsing.
- Update MVP, architecture, frontend spec, decisions, and this session log. Perform the requested manual OCR acceptance against available 260927 sample images; no automated tests.


**Achieved:**
- Refined local Tesseract parsing for exact item/category/price/quantity/total mapping, attached modifiers, decimal repair, and relative row tint. Stored row tint, strikethrough, and void-label signals; strikethrough-only voids receive low-confidence review metadata.
- Preserved ticket IDs and corrected ticket item segment reprocessing/overlap behavior. Added and populated ticket-only persistence columns and ticket detail indicators; docket extraction and CSV parsing were not changed.
- Manually accepted the available 260927 screenshots: ticket 260927-7 has 5 correctly ordered lines including void OMELETTE PARATHA and attached modifiers; ticket 260927-65 has 7 lines including void MOJITO. Ticket info fields and totals were read from the info-card screenshot. These records have no same-day matching docket, so verification correctly remains Partial.
- Reprocessed affected saved screenshots and rebuilt verification. Python syntax compilation, frontend production build, and `git diff --check` passed; no automated tests were run.


## Session 36 - 2026-09-29
**Planned changes:**
- Switch docket image extraction from NVIDIA to the existing Gemini vision path while preserving the queue, retries, Pydantic schema, audit, persistence, and verification flow.
- Configure the stable Gemini Flash endpoint and update active provider documentation.

**Achieved:**
- Routed docket jobs to Gemini structured output, kept the existing per-file job flow and strict docket data model, and labeled raw audits and job progress as Gemini.
- Set `GEMINI_MODEL=gemini-3.5-flash-lite`; the project already has `GEMINI_API_KEY` configured. The initial 3.8 Flash retry returned temporary 503 high-demand errors, so the docket job was moved to Flash-Lite. NVIDIA is no longer required by docket uploads.
- Updated active specifications and context notes. No automated tests were run.


**Session 36 provider adjustment:**
- The one prior failed docket upload was retried automatically with Gemini 3.8 Flash and received a temporary 503 high-demand response. Switched `.env` and the default to the stable `gemini-3.5-flash-lite` model, which supports image input and structured output and is designed for document parsing.
- The retry remains queued for the next worker restart. Failed jobs record the provider so this automatic migration retry occurs only once.

- After the storage and same-source merge fixes, the saved failed docket image completed through the existing worker with provider `gemini`: two docket views saved as one docket record, including order 130, date/time, table/covers, and the void-marked GAJAR KA HALWA line. Conflicting department readings remain flagged for review.


## Session 37 - 2026-09-29
**Planned changes:**
- Correct duplicate handling so only active or successfully extracted image hashes suppress repeat uploads; discard staged image files when no content is extracted.
- List saved ticket/docket image uploads with preview and per-image delete that removes linked evidence safely.
- Add copy actions to each dashboard summary box and to the selected discrepancy detail for Word-friendly plain text.

**Achieved:**
- Confirmed `test.jpeg` was already successfully extracted by Gemini and saved; its later duplicate skips were correct. Added saved-upload listing and deletion so the operator can remove that photo and its linked record before reuploading.
- No-text/empty structured extraction now fails without leaving the staged image or duplicate hash; stale hashes are discarded. Failed image files are removed unless saved evidence references them.
- Added compact copy actions on the summary boxes and discrepancy detail modal; text is formatted for pasting into Word.
- Frontend production build, backend Python syntax compilation, upload-list manual query, and `git diff --check` passed. No automated tests were run.

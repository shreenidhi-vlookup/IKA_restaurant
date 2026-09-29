# Frontend spec — CSV verification

## Main screen
Professional responsive page with branch selector and date picker at top. Branch choices are Haweli Restaurant Southall, Haweli Restaurant Norbury, and Haweli Ilford Ltd. CSV upload is the only control in step 1 and accepts one .csv. If CSV dates differ from selection, show the dates and require explicit confirmation before import. Include a **View previous records** button that lists saved CSV dates for the selected branch; each date shows its source filename and row counts, and opening it loads that date's verification boxes and discrepancy rows.

After import, render one horizontal row of five clickable boxes:

| Box | Content |
|---|---|
| Total | CSV item row count and summed quantity |
| Void | Flagged row count, amount, verified-of-total |
| Cancel | Flagged row count, amount, verified-of-total |
| Promotions | Same figures, or **Not in file** if no promotion/discount column exists |
| Status | Overall verified-of-flagged rows; say **Verified** only when all flagged rows are verified |

Boxes have a clear active state. Clicking Void, Cancel, or Promotions opens the corresponding CSV rows; Total opens all rows; Status opens unresolved flagged rows. Each row shows product, quantity, user, department, till, value, and status badge: Pending, Partial (including e.g. 1 of 2 verified), Verified, or Needs review.

Clicking a row displays a detail view. Show CSV data beside ticket and docket evidence, including ticket ID, branch/date, terminal, table, department/user, matched item void flags, totals, and ticket thumbnail; docket order/date/time, item/type, handwritten description and docket thumbnail. Null description uses a visible **No description** warning and remains Verified. List all candidates for ambiguous review states.

## Evidence upload
Below the boxes, show separate bulk controls for ticket screenshots and docket photos (up to 30 each). Uploads require selected branch/date and an imported CSV. The selected branch is retained as an association on each image record. Report per-file success/failure and automatically refresh verification after each batch. There is no Process button.

## API contract
Use POST /api/csv, GET /api/verification, GET /api/verification/dates, POST /api/upload/tickets, POST /api/upload/dockets, and /api/images/... exactly as documented in mvp_spec.md. Client only displays backend matching results; it must not infer matches.

## Evidence detail and exception UI
Ticket upload responses distinguish saved, `duplicate, skipped`, held for confirmation, and per-file failure. Held screenshots appear in a ticket-ID assignment list; entering an ID that conflicts with the selected branch/day requires a second explicit confirmation. Partial ticket-only and docket-only candidates remain visible in row details.

For each candidate, render all merged ticket fields, every item and void flag, totals, review flags, and every screenshot thumbnail. Each item includes its attached modifier and any fired row-tint, strikethrough-line, and void-label-text signals; a low-confidence strikethrough-only void is visibly marked for spot-checking. Render docket date/time, department, table, covers, staff, all item lines, handwritten description/confidence, all photo thumbnails, partial-field badges, and both readings for conflicts. A null description displays **No description**. Missing ticket or docket evidence is labeled as pending in the detail card.

Structured extraction output includes `extra_fields` as a list of labeled values. Gemini structured output is validated locally against the strict extraction schema. Ticket OCR preserves its full recognized text in the per-file audit alongside fields mapped into the ticket detail view.

Transient Gemini response guidance: docket uploads may take longer while retrying temporary 429/503 errors; the UI reports a file as failed only after its retry budget is exhausted. Local ticket OCR has no provider wait.

## Per-file extraction progress
After submitting a batch, show one progress row per image with `queued`, `processing`, `done`, or `failed`, plus the filename, final provider, and any error/message. Poll `GET /api/upload/jobs/{batch_id}` until all jobs reach a terminal status. Successful ticket extraction shows `tesseract_ocr`; successful docket extraction shows `gemini`. Exact duplicates appear as done with “Duplicate, skipped”.

Ticket screenshot extraction uses local Tesseract OCR and does not call a generative vision API. It reads positioned words with `image_to_data`; a second pass after horizontal-stroke repair only corroborates a literal `(Void)` suffix. Original pixels are compared with the adjacent item row for pink tint and checked for a horizontal strikethrough. Either tint or strikethrough marks a void; strikethrough-only rows carry a low-confidence spot-check flag. Item modifiers remain sub-fields of their parent item, and the three signals are saved per item. Per-file upload progress identifies this provider as `tesseract_ocr`. Docket extraction uses Gemini vision to read printed fields and handwritten descriptions. Runtime configuration is read from `.env`: `TESSERACT_CMD` (optional executable path), `GEMINI_MODEL`, `GEMINI_API_KEY`, `EXTRACTION_MAX_RPM`, and `EXTRACTION_CONCURRENCY`. Gemini structured docket values are validated against the strict schema before storage.

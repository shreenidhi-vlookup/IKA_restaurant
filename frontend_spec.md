# Frontend spec — CSV verification

## Main screen
The application is titled **Haveli Ticket Management**, shown in the browser tab, the header, and the footer. The page is a professional responsive layout with a branch selector and date picker at top. Branch choices are Haweli Restaurant Southall, Haweli Restaurant Norbury, and Haweli Ilford Ltd. CSV upload is the only control in step 1 and accepts one .csv. If CSV dates differ from selection, show the dates and require explicit confirmation before import. Include a **View previous records** button that lists saved CSV dates for the selected branch; each date shows its source filename and row counts, and opening it loads that date's verification boxes and discrepancy rows.

After import, render one horizontal row of five clickable boxes:

| Box | Content |
|---|---|
| Total | CSV item row count and summed quantity |
| Void | Flagged row count, amount, verified-of-total |
| Cancel | Flagged row count, amount, verified-of-total |
| Promotions | Same figures, or **Not in file** if no promotion/discount column exists |
| Status | Overall verified-of-flagged rows; say **Verified** only when all flagged rows are verified |

Boxes have a clear active state. Clicking Void, Cancel, or Promotions opens the corresponding CSV rows; Total opens all rows; Status opens unresolved flagged rows. Each row shows product, quantity, user, department, till, value, and status badge: Pending, Partial (including e.g. 1 of 2 verified), Verified, or Needs review.

Each summary dashboard box has a small copy action that copies its summary and row details as plain text. Clicking a row displays a detail view with a Copy details action for pasting the CSV, ticket, and docket evidence into Word. Show CSV data beside ticket and docket evidence, including ticket ID, branch/date, terminal, table, department/user, matched item void flags, totals, and ticket thumbnail; docket order/date/time, item/type, handwritten description and docket thumbnail. Null description uses a visible **No description** warning and remains Verified. List all candidates for ambiguous review states.

## Evidence upload
Below the boxes, show separate bulk controls for ticket screenshots and docket photos (up to 30 each). Each box shows the saved upload count; clicking it opens a manager where users can preview, replace, or delete individual images. Keep photo previews off the main page. Uploads require selected branch/date and an imported CSV. The selected branch is retained as an association on each image record. Report per-file success/failure and automatically refresh verification after each batch. There is no Process button.

Each upload box also accepts drag-and-drop alongside the Browse button: dragging image files over a box highlights it as a drop zone using the existing active-box border/background, and dropping uploads the files. The upload buttons have a subtle hover state (existing sage border/soft background) and a pressed/active state, using only existing theme tokens. The file picker is restricted to PNG/JPG/WEBP. A best-effort UI-side guard shows an inline warning when a file whose name suggests the other document type (for example a file named "docket…" dropped on the ticket box) is dropped or selected in the wrong box; because tickets and dockets are both plain images, this filename check is a best-effort signal only and not a guarantee.

Saved ticket and docket extraction records are displayed in their own tables for the selected branch/day. Docket rows include extracted item text, nested item lines with void markers, handwritten reason, and review/conflict/partial-field indicators.

## API contract
Use POST /api/csv, GET /api/verification, GET /api/verification/dates, POST /api/upload/tickets, POST /api/upload/dockets, GET/DELETE /api/uploads, and /api/images/... exactly as documented in mvp_spec.md. Client only displays backend matching results; it must not infer matches.

## Control states, loading, and disabled guidance
Every interactive control on the main screen shares one interaction treatment: the branch dropdown, business date picker, Choose CSV, View previous records, the ticket/docket Browse buttons, and the utility buttons (Copy, Close, Cancel, Assign ticket ID, Confirm and import, Replace, Delete). On hover a filled control darkens slightly via `filter: brightness(.93)`, and on press it uses `brightness(.88)` with a small downward nudge. Because the fill is a solid colour, state changes are driven by the brightness filter rather than a border or background swap, so no additional colour is introduced and every state remains legible. All controls transition `filter`, `box-shadow`, `transform`, `background-color`, `border-color`, and `color`, so no state snaps into place on hover. A filled control takes a white focus ring, since the default 3px accent ring is not visible against the fill. The document pins `color-scheme: light` and strips the platform `appearance` from buttons so a dark OS can never paint a default button surface over a transparent control.

**One button colour.** Every action control, including the Restaurant branch select and the Business date picker, uses the same primary orange fill as Choose CSV. The single exception is the View/manage control, which keeps its own secondary colour to stay visually distinct from the actions. The select and date picker are a matched pair and keep their native dropdown and calendar affordances, with the calendar indicator inverted so it stays visible on the fill.

**Guard messages never move the control.** A disabled-guard message must be rendered inside a column wrapper beneath its control, never as a sibling inside a `display: flex` row. Injecting a message as a new flex child of the CSV card re-flowed the row and made the button jump sideways on hover, which is the glitch the operator reported. The label, its message, and the filename are wrapped together so the button holds its position and the message appears underneath it.

**Disabled controls explain themselves.** A control that cannot run keeps the existing muted opacity treatment, but must never be a dead `not-allowed` cursor. On hover, and on click for touch devices with no hover, an inline message appears next to the control naming the actual blocker, and the cursor becomes a help cursor. Messages are derived from real gating, not assumed: Choose CSV and View previous records require a branch ("Select a restaurant branch first."); View/manage requires a branch; ticket and docket upload require a branch and then a completed Step 1 CSV import for the selected date ("Import a CSV for this date first (Step 1)."). While a control is genuinely in progress the spinner is the explanation, so no gating message is shown.

**One loading indicator.** A single circular `Spinner` component is reused everywhere and is drawn with `currentColor`, so it automatically adopts the surrounding text color instead of introducing a second style. It appears for CSV processing, for a submitted ticket/docket batch while any per-file job is still queued or processing, for loading previous records, and for an in-progress image replace.

**View/manage is a real button.** The ticket and docket saved-count control is a styled button matching the existing secondary button pattern, not underlined inline text. It is the one control that is not the primary orange fill, and its action is unchanged.

## Black row overlay fix
The document pins `color-scheme: light` and sets `appearance: none` on buttons. The interactive table rows and summary boxes are `<button>` elements styled `background: transparent`; without these, the platform button surface sits underneath that transparent background and renders near-black in a dark-mode OS, which showed as a black overlay on a row. The docket nested item table also gained the missing scroll container and an opaque table background, so an expanded item list can no longer overflow its cell and paint transparent rows over its neighbours.

## Image preview, caching, and retention
Not implemented; reported separately. Preview images are served from `/api/images/...` via FastAPI `StaticFiles`, which returns `ETag`/`Last-Modified` and supports `304`, but sends no `Cache-Control`, so browser caching is heuristic and every page load re-fetches a large share of the image set. A stored image is written at upload time and then deleted by the worker when extraction fails and nothing references it, while its `extraction_jobs` row and filename remain, which is why a filename can persist while its image is blank. No retention or auto-delete job exists; the only deletions are the failed-duplicate cleanup and `_remove_image_file`.

## Evidence detail and exception UI
Ticket upload responses distinguish saved, `duplicate, skipped`, held for confirmation, and per-file failure. Held screenshots appear in a ticket-ID assignment list; entering an ID that conflicts with the selected branch/day requires a second explicit confirmation. Partial ticket-only and docket-only candidates remain visible in row details.

For each candidate, render all merged ticket fields, every item and void flag, totals, review flags, and every screenshot thumbnail. Each item includes its attached modifier and any fired row-tint, strikethrough-line, and void-label-text signals; a low-confidence strikethrough-only void is visibly marked for spot-checking. Render docket date/time, department, table, covers, staff, all item lines, handwritten description/confidence, all photo thumbnails, partial-field badges, and both readings for conflicts. A null description displays **No description**. Missing ticket or docket evidence is labeled as pending in the detail card.

Structured extraction output includes `extra_fields` as a list of labeled values. Gemini structured output is validated locally against the strict extraction schema. Ticket OCR preserves its full recognized text in the per-file audit alongside fields mapped into the ticket detail view.

Transient Gemini response guidance: docket uploads may take longer while retrying temporary 429/503 errors; the UI reports a file as failed only after its retry budget is exhausted. Local ticket OCR has no provider wait.

## Per-file extraction progress
After submitting a batch, show one progress row per image with `queued`, `processing`, `done`, or `failed`, plus the filename, final provider, and any error/message. Poll `GET /api/upload/jobs/{batch_id}` until all jobs reach a terminal status. Successful ticket extraction shows `tesseract_ocr`; successful docket extraction shows `gemini`. Exact duplicates appear as done with “Duplicate, skipped”.

Ticket screenshot extraction uses local Tesseract OCR and does not call a generative vision API. It reads positioned words with `image_to_data`; a second pass after horizontal-stroke repair only corroborates a literal `(Void)` suffix. Original pixels are compared with the adjacent item row for pink tint and checked for a horizontal strikethrough. Either tint or strikethrough marks a void; strikethrough-only rows carry a low-confidence spot-check flag. Item modifiers remain sub-fields of their parent item, and the three signals are saved per item. Per-file upload progress identifies this provider as `tesseract_ocr`. Docket extraction uses Gemini vision to read printed fields and handwritten descriptions. Runtime configuration is read from `.env`: `TESSERACT_CMD` (optional executable path), `GEMINI_MODEL`, `GEMINI_API_KEY`, `EXTRACTION_MAX_RPM`, and `EXTRACTION_CONCURRENCY`. Gemini structured docket values are validated against the strict schema before storage.

## Local network preview
The default Vite development server binds to 0.0.0.0:5173 with strict port selection; its /api proxy targets 127.0.0.1:8000 on the host. A same-subnet client opens the host Ethernet IPv4 address over HTTP.

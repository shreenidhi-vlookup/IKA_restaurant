# FRONTEND SPEC — TIL SYSTEM

> This is the contract between backend and UI. If the backend changes a
> field name, endpoint, or flow, this file must be updated in the same
> session — don't let it drift from what the API actually returns.

## 1. Screens

### Screen 1 — Upload
- “Upload screenshots in bulk” control for ticket screenshots using `files`,
  with per-screenshot success/failure state and merged Ticket ID/item counts
  in the response
- Separate bulk docket image control using `files`, with per-image
  success/failure state and visible manual-review flags
- Shows upload progress / basic success-fail state per image
- On success, extracted rows appear in the table (Screen 2)

### Screen 2 — Parsed records
The header exposes separate `Tickets`, `Dockets`, and `Voids tally` views.
Parsed ticket and docket tables are collapsed by default after upload. Each
upload panel exposes a `Show data` button after a successful result; clicking
it reveals that dataset and toggles it closed again.

Tickets renders one row per parsed ticket from `/api/tickets`, with columns:
Ticket ID, Uploaded, Restaurant, Date, Terminal, Table, Department, User, Payment
Status, Credit Card Amount, Items, Ticket Total, Grand Total, and Charged.
The Items cell contains an expandable nested item table with item, category,
price, qty, total, and void marker. Ticket CSV export uses
`/api/tickets/export`.
Ticket screenshots uploaded through either ticket control or a structure-
detected generic image upload appear here immediately; they do not appear in
the legacy bill-image entries table. The Ticket Number column displays the
complete hyphenated value, such as `260920-143`.

Dockets renders `/api/dockets` separately, with columns: Order No, Date, Time,
Item, Discrepancy Type, and Handwritten Reason. The
order number is explicitly labelled as partial and never displayed as Ticket
ID. Review-flagged rows are visibly distinct. Docket CSV export uses
`/api/dockets/export`.

The legacy generic entries table is not rendered for ticket or docket data.

### Screen 3 (optional, only if needed for MVP) — Description prompt
- Simple modal/form: shows the image, lets operator type a description,
  saves back to the row.

### Screen 4 — Voids reconciliation
- A Voids view calls `GET /api/reconcile/voids` and renders two aligned
  columns: the voided ticket item on the left and docket evidence on the right.
- Each row shows `row_position`, Ticket ID, item name/quantity/price/total,
  docket order/date/time/item, and `handwritten_reason` when available.
- Rows with `status: matched` appear first. `needs_review` rows show every
  `docket_candidates` candidate and an explicit collision message. `unmatched`
  rows show an explicit no-docket state; the right cell must not look blank.
- Summary counts show total void items, matched, needs review, and unmatched.

### Screen 5 — Sales report upload (long slip + Daily Exception Report)
- Step 1 is scope: a **branch** selector (options come from
  `GET /api/restaurants`, never hardcoded) and a **working day** date input.
  Both scope everything below, including the ticket and docket tables. The
  slip's own printed date is never used as the scope.
- Step 2 is the two comparison sources, using the EXISTING "Upload long bill
  slip" and "Upload Excel" controls in the Comparison source panel — do not add
  a second, duplicate upload UI:
  - **Source 1 — long slip**: a photo of the till's printed Work Period Report,
    read by vision.
  - **Source 2 — Excel**: the Daily Exception Report (`.xlsx`) row-level log.
  Either may be uploaded alone, or both together.
- `POST /api/upload/sales-reports` with multipart `file`, `excel_file`,
  `restaurant`, `report_date`, `confirm`.
- When both sources are chosen and the void amounts disagree, the backend
  returns `409 {status, message, mismatches[], slip, excel}`. Show the
  per-metric disagreements and require the operator to choose
  **Store the long slip** or **Store the Excel report**
  (`confirm=slip|excel`) before anything is stored. Nothing is stored until
  then. The client must read the 409 body itself (`uploadSalesReport` returns
  `{conflict}`) because the shared `apiFetch` helper flattens a structured
  `detail` into a string.
- On success show the stored report: branch, working day, source
  (`slip` / `excel` / `slip+excel` / `slip (confirmed)` /
  `excel (confirmed)`), extraction method (`vision` / `ocr_fallback` / `xlsx`),
  cross-verification state, the per-department totals, and the Excel figures
  (void rows, rows with no adjustment type, rows skipped as out of scope).

### Screen 6 — Process and the reconciliation dashboard
- Step 3 is a **Process** button, disabled until a branch is chosen. It calls
  `POST /api/sales-reports/process` with `{restaurant, date}`. Every figure on
  the dashboard comes from that one payload — the UI does no client-side
  matching or counting, and recalculates on each run.
- Changing the branch or the working day clears the saved report and the last
  dashboard, so a stale result is never shown against a new scope.
- The dashboard shows, in order: source chips (slip uploaded?, Excel uploaded?,
  cross-verified?), a **missing** notice naming every absent input, six stat
  cards (void items in tickets, dockets filed on this day, total matched voids,
  dockets used in matches, unresolved voids, anomaly), Voids in the long slip,
  Voids in Excel, the Bill vs Excel check, reconciliation by department, both
  unmatched lists, and discounts/promotions marked not yet reconciled.
- Dockets carry no restaurant field, so docket figures are **date-only**; the
  dashboard says so. A matched docket may carry a printed date other than the
  working day, so "dockets filed on this day" and "dockets used in matches" are
  separate cards.
- The Excel void **count** comparison is displayed but labelled not scored, with
  the reason: it is not yet confirmed whether the slip counts voided items or
  voided bills, and one bill can own several void rows.
- **Every absent input has a named empty state** — a panel that says which file
  or record type is missing — so a missing input is never rendered as a zero
  that reads like a real measurement.

### Screen 6 — Sales-report aggregate reconciliation
- Calls `GET /api/sales-reports/reconcile`. Per restaurant/date/department it
  shows reported vs matched vs unresolved voids, an anomaly badge when
  `matched > reported`, and the untracked note for discounts/promotions
  (`tracked: false` — the report states them but the pair tally does not
  prove them; display as a coverage note, never as a matched figure).
- Exports via `GET /api/sales-reports/export` (one row per department).

## 2. States to handle
- Empty state (no bills uploaded yet)
- Loading state (extraction in progress)
- Error state (extraction failed / bad image)
- "Needs description" state (distinct from normal rows)
- Backend `status` values feed the row/table styling: `matched`,
  `needs_description`, `needs_ticket_number`, `needs_restaurant`,
  `needs_discrepancy_type`, `needs_review`.

## 3. Visual bar
- Professional, clean — not a bare unstyled table. Doesn't need to be
  elaborate, but should look like a real internal tool, not a prototype.

## 4. API contract (confirmed against the running backend)
| Action | Method | Endpoint | Notes |
|---|---|---|---|
| Upload image | POST | `/api/upload` | Multipart field **`file`** (singular). A full hyphenated Ticket ID is routed to `ticket_records`; unrecognized non-ticket images are rejected instead of being written to the docket table. |
| Upload image batch | POST | `/api/upload/bulk` | Multipart field **`files`** (plural, up to 30). Ticket-detected images use the ticket pipeline; non-ticket images are reported as failures and never enter a dedicated record table. |
| Upload ticket screenshots | POST | `/api/upload/tickets` | Multipart field **`files`** (plural, up to 30 screenshots). Each success returns the full `ticket_id`, item count, and screenshot count. |
| Upload docket images | POST | `/api/upload/dockets` | Multipart field **`files`** (plural, up to 30 images). Each success returns `order_number`, `date`, `time`, `item`, `discrepancy_type`, `description`, and review fields. |
| Get parsed tickets | GET | `/api/tickets` | Returns `ticket_id`, `uploaded_at` (latest screenshot upload/merge time), scalar metadata, `items[]` from the ticket item sub-table, `extra_fields`, and screenshot filenames. |
| Get parsed dockets | GET | `/api/dockets` | Returns `order_number`, `date`, `time`, `item`, `discrepancy_type`, `description`, `extra_fields`, and review fields. |
| Export parsed tickets | GET | `/api/tickets/export` | CSV with one row per parsed ticket and an Items column containing the flattened item list. |
| Export parsed dockets | GET | `/api/dockets/export` | CSV with docket order/date/time/item/discrepancy/handwriting/review fields. |
| Get void reconciliation | GET | `/api/reconcile/voids` | Returns `{rows, summary}`. Rows are already aligned and sorted by `row_position`; each contains `status`, `match_confidence`, `ticket`, `docket`, and `docket_candidates`. |
| Export void reconciliation | GET | `/api/reconcile/voids/export` | Downloads the same aligned rows and order as the JSON endpoint. The Voids view must use this endpoint instead of `/export`. |
| Upload sales report | POST | `/api/upload/sales-reports` | Multipart `file` (long slip image, optional), `excel_file` (Daily Exception Report .xlsx, optional); at least one required, and `report_date` (working day) is always required. Optional form fields `restaurant` (branch) and `confirm` (`slip` or `excel`). On a slip/Excel void-amount mismatch without `confirm` returns `409 {status, message, mismatches, slip, excel}` and stores nothing. |
| Get sales reports | GET | `/api/sales-reports` | Returns `restaurant`, `report_date`, `departments[]` (name + voids/discounts/promotions/cancelled count+amount), `source`, `cross_verified`, `confirmed_source`, `extraction_method`, `image_filename`, `excel_filename`, `extra_fields`, and the Excel `void_rows` / `unfilled_rows` / `skipped_rows` counters. |
| Get branches | GET | `/api/restaurants` | Always returns Ilford, Southall and Norbury, each with the till `restaurant_names` behind it. The UI renders these options and never hardcodes branches. |
| Process dashboard | POST | `/api/sales-reports/process` | Body `{restaurant, date}`. Returns every dashboard figure: `report`, `bill`, `excel`, `bill_vs_excel`, `counts`, `departments`, `totals`, `unmatched_ticket_voids[]`, `unmatched_dockets[]`, `coverage`, `docket_scope`, `missing[]`. Recomputed per run. |
| Sales report aggregate | GET | `/api/sales-reports/reconcile` | Returns per-report per-department `voids {reported, matched, unresolved, anomaly}` and `discounts/promotions {reported, tracked: false, note}` plus pair-tally `summary` and `coverage`. |
| Export sales reports | GET | `/api/sales-reports/export` | CSV with one row per department: restaurant, date, source, cross_verified, department, and the four metric count/amount pairs. |
| Get table rows | GET | `/api/entries?restaurant=&ticket_number=` | Query params optional; backend matches by exact value. Returns an array of `{id, restaurant, ticket_number, discrepancy_type, extracted_text, description, status, extra_fields, image_filename, blocks?}`. `blocks` is additive structured segmentation (header / line_items / discrepancies / totals / payment) that the frontend may ignore. |
| Reconcile tickets to image entries | POST | `/api/reconcile` | Body `{tickets: [{ticket_number, restaurant, date, time, amount, discrepancy_type, ...}], entries: [{id, ticket_number, restaurant, image_filename, extracted_text, description, ...}]}`. Returns `{results: [{ticket_number, restaurant, status, match_confidence, matched_entry_id, reason_provided, issue_addressed, handwritten_note, evidence}], summary: {Matched, Missing, Needs Review}}`. Ticket status is separate from entry status and must be displayed with its own column/filter. |
| Update description | PATCH | `/api/entries/{id}` | Body `{description?, status?}`. Returns the updated row (same shape as `/entries` rows). |
| Export CSV | GET | `/api/export?restaurant=&ticket_number=` | Same filters as `/entries`. Returns a CSV file with columns `restaurant, ticket_number, discrepancy_type, description, status, image_filename`. Browser downloads the file. |

### Frontend integration notes
- All routes live under the `/api` prefix (confirmed in `app/main.py`). The
  Vite dev server proxies `/api` to `http://localhost:8000` because the
  backend has no CORS middleware.
- `/upload` accepts one file per request in the singular `file` field. For
  true bulk upload, `/upload/bulk` accepts up to 30 files in the plural
  `files` field and reports success/failure independently for each filename.
  Both routes use the same synchronous extraction pipeline. The existing UI
  may continue sending one request per selected image; a bulk UI should
  refresh `/entries` after the bulk response rather than poll.
- Division 4c adds ticket-level reconciliation. The UI needs a separate
  reconciliation table or section showing `status` values `Matched`, `Missing`,
  and `Needs Review`, plus `match_confidence`, `reason_provided`, and
  `issue_addressed` columns or filters. These are different from the image
  entry `status` values (`matched`, `needs_description`, etc.) and must not be
  collapsed into one field.
- `/entries` returns no `thumbnail` field and the backend serves no image
  bytes; the "Image" column shows `image_filename` instead.
- Restaurant filter options come from the restaurant values in the
  `/entries` data (static placeholder names are shown only while the table
  is empty).
- The ticket-number search maps to the `ticket_number` query param (exact
  match), so a partial number returns no rows until it is fully entered.
- `/entries` responses may include an additive `blocks` field (structured
  line items / discrepancies / totals / payment). Render only what the table
  needs today; ignore unknown fields so backend growth stays non-breaking.
- Ticket upload results are authoritative for the merged ticket count. The UI
  should show the returned `ticket_id`, item count, screenshot count, and each
  failed screenshot; it should not create one UI ticket row per screenshot.
- Docket upload must display `docket_order_no` as a weak/partial match key,
  never as a full Ticket ID. It must keep `handwritten_reason` separate from
  printed fields and visibly mark `review_required` records.
- The Voids view must never independently sort or match rows in the browser;
  it renders the backend `row_position` order and sends void exports to the
  reconciliation export endpoint. The Tickets and Dockets views refresh their
  parsed endpoint after their corresponding bulk upload completes.
- The sales-report upload must show a restaurant selector when the printed
  report has no recognizable restaurant (the backend returns 400 in that
  case) and must render the 409 mismatch detail as a conflict the operator
  resolves with the `image` / `csv` choice — not as a generic error.
- `GET /api/sales-reports` returns departures of `departments[]` as flat
  objects; the aggregate view uses `GET /api/sales-reports/reconcile` and
  must treat `tracked: false` for discounts/promotions as a coverage note,
  never a provable matched count.

## 5. Changelog
| Date | Change | Reason |
|------|--------|--------|
| —    | Initial spec created | — |
| 2026-09-21 | Added frontend integration notes for upload and export behavior | Keep the UI contract honest while backend response shapes remain TBD |
| 2026-09-21 | Confirmed and finalized the API contract (section 4) against the running backend; updated column list (Image/Image column, verbatim statuses, extra_fields surfacing) and Frontend integration notes | Frontend is now wired end-to-end to the real backend; earlier "TBD" assumptions (upload field `files`, thumbnail field, unfiltered export) were corrected to match actual API behavior |
| 2026-09-21 | Documented the additive `blocks` field on `/entries` rows | Backend now persists per-entry structured segmentation (block JSON); frontend ignores it until it needs it |
| 2026-09-21 | Documented synchronous `/upload/bulk` with per-image success/failure results | Backend now accepts up to 30 images without changing the existing single-upload contract |
| 2026-09-21 | Replaced the stale single-entry-table contract with separate parsed Tickets, Dockets, and Voids tally views | Operators need to inspect extracted ticket/docket fields directly and export each record type without losing void alignment |
| 2026-09-22 | Finalized dedicated table columns: one row per ticket with a flattened Items cell and six docket columns; generic entries are not rendered | The UI must match the strict ticket/docket schemas and avoid generic raw-text presentation |
| 2026-09-23 | Added Sales report upload and aggregate reconciliation screens and their API contract rows | Division 6 ground truth needs explicit operator cross-verification handling and a reported-vs-matched view | frontend_spec.md |
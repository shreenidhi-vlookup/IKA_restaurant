# The Floor: implementation and review checklist

The connected V2.1 interface is the default application at `/`, with `#overview`, `#imports`, `#tickets`, `#verification`, and `#reports` sections. `/preview/v2` remains a compatibility alias for the same interface. The original application is available at `/legacy`. Obsolete `/design/*` prototype URLs redirect to `/`. All V2.1 sections share API-compatible branch and local-calendar business-date state.

## Implemented against existing functionality

- Imports: till CSV replacement, date-mismatch confirmation/cancel, separate ticket-report CSV, unpaid details/copy, ticket screenshot and docket image pickers/drop areas, file limits and validation, asynchronous extraction jobs, errors/retry, saved-image previews/deletion/replacement, safe replacement retention on failure, unassigned screenshot resolution and mismatch confirmation, previous till-import dates.
- Tickets: actual ticket/docket records, searches and filters, item details, extraction flags/conflicts/partial fields, evidence galleries, empty-ticket details/copy, readable zero values and original identifiers.
- Verification: original five summary categories, category and status filtering, matching candidates, ticket/docket details and evidence, five original category copies plus evidence-detail copy. Together with empty-ticket and unpaid-ticket copy, all eight original copy formats are retained.
- Overview: real import/processing activity, outstanding flagged CSV rows, unresolved screenshot IDs, incomplete evidence pairs, extraction review counts, derived daily workflow checks, failed session submissions.
- Reports: selected branch/date workflow records, original CSV summary and copy, flagged-row status record, saved branch import history with date selection, branch/date-scoped discrepancy and processing charts below the main reports.

## Data semantics and backend limits

- Till rows use the backend's selected-date scope, including confirmed imports whose CSV row dates differ. Tickets and evidence retain the existing endpoints' date semantics.
- Extraction completion is separate from CSV verification. Evidence-pair counts describe candidate records, not confirmed image-file availability or manual approval.
- Unpaid ticket-report results exist only in the current session and reset on branch/date changes. Missing results display as unavailable, never as zero unpaid tickets.
- Daily checks are derived read-only indicators. No new approval, persisted sign-off, reviewer audit, authentication, report export, or assignment API is invented.
- Discrepancy charts count flagged CSV row/type combinations. A row with multiple flags can contribute to multiple categories.
- Failed data loads display errors; existing snapshots are explicitly labelled as last successfully loaded records.

## Automated verification

Node tests cover controller API payloads, context changes/races, confirmation flows, upload validation, polling recovery, safe replacements, records/filters, clipboard handling and exact original eight copy outputs, report calculations, history recovery/invalidation, and shared selectors. The existing Python suite covers API/database/upload/matching behavior in isolated temporary storage. Production build and lint are also checked.

Browser interaction acceptance remains a manual review item: exercise each picker/drop area, native confirmation/dialog, clipboard action, small-screen layout, and keyboard navigation with representative restaurant data. Automated controller tests substitute request results; they do not constitute a browser-to-live-backend end-to-end test. Existing live endpoints are checked read-only, without importing or deleting real evidence.

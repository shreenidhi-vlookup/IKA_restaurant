# CONTEXT.md — START HERE

This is the only file a new session/agent needs to open first. Read this, then
follow the links below in order. Do not start writing code before doing this.

## Project
**TIL SYSTEM** — a discrepancy-checking tool for restaurant bills.
Three restaurants send bill images. An operator reconciles void / discount /
promotion discrepancies against tickets in a custom app, using the ticket
number to find the matching bill image. If a matched image has no
description, the system must prompt for one.

## Read in this order
1. `rules.md` — non-negotiable constraints. Everything else is subordinate to this.
2. `MVP_spec.md` — what we're building and why.
3. `architecture.md` — how the codebase is laid out.
4. `frontend_spec.md` — UI contract for the teammate building the frontend.
5. `decisions.md` — locked decisions. If a decision here conflicts with any
   other file, `decisions.md` wins and the other file is out of date — fix it.
6. `session_log.md` — history of what's been done, session by session.

## Current status
> Update this section at the end of every session. This is the fastest way
> for the next session to know where things stand.

- Phase: **Sales report two-source upload + Process dashboard built and
  hand-verified; awaiting a real long slip + real Daily Exception Report pair**
- Last session: Session 27 — 2026-09-28
- Division 6 now has two independent sources: the **long slip** image (the till
  printed Work Period Report, per-department Voids/Discounts/Promotions/
  Cancelled, read by vision) and the **Excel Daily Exception Report** (`.xlsx`,
  a row-level log). Source 2 is NOT a mirrored export of the slip. They are
  cross-verified by branch + day void **amount** before anything is stored; the
  void **count** comparison is displayed but explicitly not scored until it is
  empirically confirmed. A mismatch stores nothing until the operator confirms
  which source wins.
- `POST /api/sales-reports/process` is the single source of every Process
  dashboard figure, recomputed per run, with named empty states for every
  absent input. `GET /api/restaurants` always returns Ilford / Southall /
  Norbury so the UI never hardcodes branches.
- Two scoping rules were corrected and affect real data: a ticket's working day
  comes from its Ticket ID's `YYMMDD` prefix (not the printed date — every
  stored ticket prints a date one day ahead of its id prefix), and the slip's
  printed date never defines the report's day (the operator's selection does).
- The `final` frontend description modal and keyboard navigation were preserved;
  the dead "Upload Excel" / "Upload long bill slip" controls were wired rather
  than duplicated. Frontend lint and build pass. `stash@{0}` still holds the
  pre-`final` sales-report frontend.
- **Waiting on the user for real-sample acceptance:** a real long slip photo and
  a real Daily Exception Report for the SAME branch and day, plus confirmation
  of what the slip's void count actually counts (items or bills) so the count
  comparison can be scored. A `GEMINI_API_KEY` is in the untracked `.env` (never
  commit it). Gemini `gemini-2.5-flash` returns HTTP 404; the default is now
  `gemini-3.8-flash`, and whenever vision is unavailable the paths fall back to
  Tesseract+regex with the `extraction_method` fallback visibly recorded.
- No automated tests exist or were added; the work was verified by minimal
  manual checks (compile/import plus the endpoint scenarios listed in
  `session_log.md` Session 27).

## Golden rule for every session
1. Before writing any code: write a "Planned changes" entry in `session_log.md`.
2. Do the work.
3. Write an "Achieved" entry in the same session_log.md entry.
4. If any decision changed, update `decisions.md` AND propagate that change
   into `MVP_spec.md` / `architecture.md` / `frontend_spec.md` — do not leave
   stale info in any of them.
5. Update the "Current status" block above.
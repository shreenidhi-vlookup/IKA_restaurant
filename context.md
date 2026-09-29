# CONTEXT - TIL CSV Verification

This project verifies discrepancies from restaurant till CSVs against extracted POS tickets and handwritten docket evidence.

Read `rules.md`, `MVP_spec.md`, `architecture.md`, `frontend_spec.md`, `decisions.md`, and `session_log.md` before further work.

## Current status
- Phase: CSV-driven verification UI with local OCR for POS ticket screenshots and Gemini vision extraction for handwritten dockets. Docket extraction manually exercised against the previously failed screenshot using Gemini Flash-Lite.
- Last session: Session 36 - 2026-09-29.
- Ticket OCR uses local pytesseract with the installed Tesseract 5 engine (`TESSERACT_CMD` is set in the project `.env`). It stores exact ticket fields, item modifiers, and row tint/strikethrough/label signals.
- Docket extraction uses Gemini Flash-Lite (`GEMINI_API_KEY` / `GEMINI_MODEL`) with the existing queue and storage workflow; ticket OCR and CSV parsing are unchanged.

## Session rule
Record Planned changes before code and an honest Achieved entry after work. Keep decisions synchronized across all three specs. Do not run automated tests; user performs manual acceptance.

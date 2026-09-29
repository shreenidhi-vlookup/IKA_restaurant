# TIL CSV Verification UI

Select a restaurant branch and date, upload one till CSV, review the five summary boxes, then upload ticket screenshots and docket photos. The UI refreshes verification after each saved image batch; matching is provided only by the backend.

Backend API details and the exact box/status behavior are in ../frontend_spec.md. Start the Vite development server with npm run dev; it proxies /api to the FastAPI service at http://localhost:8000.

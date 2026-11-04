# Haveli Ticket Management

Select a restaurant branch and date, upload one till CSV, review the five summary boxes, then upload ticket screenshots and docket photos. The UI refreshes verification after each saved image batch; matching is provided only by the backend.

The connected V2.1 interface is the default application at http://localhost:5173/ (also available at /preview/v2). The original application remains available at /legacy. Obsolete /design/* prototype URLs redirect to the default application.

Backend API details and the exact box/status behavior are in ../frontend_spec.md. Start the Vite development server with npm run dev; it proxies /api to the FastAPI service at http://localhost:8000.

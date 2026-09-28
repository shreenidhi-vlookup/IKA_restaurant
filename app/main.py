import dotenv
dotenv.load_dotenv()

from fastapi import FastAPI
from app.api.upload import router as upload_router
from app.api.entries import router as entries_router
from app.api.export import router as export_router
from app.api.reconciliation import router as reconciliation_router
from app.api.void_reconciliation import router as void_reconciliation_router
from app.api.records import router as records_router
from app.api.sales_report_reconciliation import router as sales_report_reconciliation_router
from app.storage.db import init_db

app = FastAPI(title="TIL SYSTEM Backend", version="0.1.0")
init_db()

# Include routers
app.include_router(upload_router, prefix="/api")
app.include_router(entries_router, prefix="/api")
app.include_router(export_router, prefix="/api")
app.include_router(reconciliation_router, prefix="/api")
app.include_router(void_reconciliation_router, prefix="/api")
app.include_router(records_router, prefix="/api")
app.include_router(sales_report_reconciliation_router, prefix="/api")

@app.get("/")
async def root():
    return {"message": "TIL SYSTEM Backend is running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}
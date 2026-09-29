from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

from app.api.image_upload import router as image_upload_router, start_extraction_workers, stop_extraction_workers
from app.api.verification import router as verification_router
from app.storage.db import init_db

app = FastAPI(title="TIL CSV Verification", version="1.0.0")
init_db()
app.include_router(verification_router, prefix="/api")
app.include_router(image_upload_router, prefix="/api")
app.mount("/api/images/ticket_screenshots", StaticFiles(directory="data/uploads/ticket_screenshots"), name="tickets")
app.mount("/api/images/dockets", StaticFiles(directory="data/uploads/dockets"), name="dockets")


@app.on_event("startup")
async def startup_extraction_queue():
    await start_extraction_workers()


@app.on_event("shutdown")
async def shutdown_extraction_queue():
    await stop_extraction_workers()


@app.get("/")
async def root():
    return {"message": "TIL CSV verification service is running"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}

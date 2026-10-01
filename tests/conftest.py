"""Shared test setup.

The app stores everything under relative ``data/`` paths, so the whole suite runs
from a throwaway working directory; the real data/til_system.db and uploads are
never touched. Vision/OCR providers are replaced by fakes that read a JSON payload
from the uploaded bytes, so each test fully controls what "the image" contains.
"""
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(PROJECT_ROOT))

_WORKDIR = Path(tempfile.mkdtemp(prefix="ika-tests-"))

BRANCH = "Leeds"
DATE = "2026-09-30"
TICKET_ID = "260930-12"


TABLES = ("ticket_items", "ticket_records", "docket_records", "csv_rows", "upload_audits", "csv_imports",
          "unassigned_screenshots", "upload_hashes", "extraction_jobs")


def pytest_configure(config):
    # Runs after pytest has resolved test paths but before any test module (and
    # therefore the app, which touches data/ on import) is imported.
    (_WORKDIR / "data" / "uploads" / "ticket_screenshots").mkdir(parents=True, exist_ok=True)
    (_WORKDIR / "data" / "uploads" / "dockets").mkdir(parents=True, exist_ok=True)
    os.chdir(_WORKDIR)
    os.environ["EXTRACTION_CONCURRENCY"] = "2"
    # TEST_DATABASE_URL runs the suite against Postgres; otherwise a throwaway SQLite
    # file is used. The real DATABASE_URL from .env is never used by tests.
    test_url = os.getenv("TEST_DATABASE_URL", "").strip()
    if test_url:
        database_name = test_url.rsplit("/", 1)[-1].split("?", 1)[0]
        if "test" not in database_name:
            raise pytest.UsageError(f"TEST_DATABASE_URL database {database_name!r} must contain 'test'; its tables are wiped")
    # Set even when empty: load_dotenv() in app.main never overrides an existing variable.
    os.environ["DATABASE_URL"] = test_url


def pytest_report_header(config):
    return f"database backend: {'postgres' if os.getenv('DATABASE_URL') else 'sqlite (temporary file)'}"


_schema_ready = False


def pytest_unconfigure(config):
    os.chdir(PROJECT_ROOT)
    shutil.rmtree(_WORKDIR, ignore_errors=True)


@pytest.fixture(autouse=True)
def fresh_state():
    """Every test starts with an empty database and empty upload folders."""
    global _schema_ready
    from app.api import image_upload
    from app.storage import db

    if db.is_postgres():
        with db.get_db_connection() as conn:
            if not _schema_ready:
                for table in TABLES:
                    conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
                conn.commit()
                db.init_db()
                _schema_ready = True
            else:
                conn.execute(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE")
                conn.commit()
    else:
        db_path = Path(db.DATABASE_PATH)
        if db_path.exists():
            db_path.unlink()
        db.init_db()
    for folder in (image_upload.TICKET_DIR, image_upload.DOCKET_DIR):
        for name in os.listdir(folder):
            os.remove(os.path.join(folder, name))
    yield


# ---------------------------------------------------------------- fake images

def fake_image(kind: str, parsed: dict | None = None, *, nonce: str = "") -> bytes:
    """Bytes the fake classifier/extractors understand. ``kind`` is what the
    classifier will detect: 'ticket', 'docket' or 'uncertain'; ``parsed`` is what
    extraction returns (empty means nothing readable on the image)."""
    return json.dumps({"kind": kind, "parsed": parsed or {}, "nonce": nonce}).encode()


def ticket_parsed(ticket_id=TICKET_ID, items=None, **overrides):
    parsed = {
        "ticket_id": ticket_id, "branch": BRANCH, "date": "30/9/2026", "terminal": "T1",
        "table": "4", "department": "Bar", "user": "Alice", "payment_status": "Paid",
        "credit_card": None, "ticket_total": "10.00", "grand_total": "10.00", "charged": "10.00",
        "extra_fields": [],
        "items": items if items is not None else [
            {"name": "Burger (Void)", "qty": "1", "price": "10.00", "total": "10.00", "is_void": True,
             "signals": {"row_tint": True, "strikethrough_line": True, "void_label_text": True}},
        ],
    }
    parsed.update(overrides)
    return parsed


def docket_view(order="12", items=None, **overrides):
    view = {
        "order_number": order, "date": DATE, "time": "19:05", "department": "Bar", "table": "4",
        "covers": "2", "staff_name": "Alice", "description": "customer changed mind",
        "description_confidence": 0.9, "partial_fields": [], "extra_fields": [],
        "items": items if items is not None else [
            {"name": "Burger", "quantity": 1, "is_void": True, "marker_type": "void"},
        ],
    }
    view.update(overrides)
    return view


class FakeProviders:
    def __init__(self):
        self.gemini_calls = []
        self.ocr_calls = []
        self.gemini_error = None

    @staticmethod
    def _load(path):
        with open(path, "rb") as handle:
            return json.loads(handle.read())

    def classify(self, path):
        kind = self._load(path)["kind"]
        return kind, f"fake classifier says {kind}"

    def ocr(self, path):
        self.ocr_calls.append(path)
        payload = self._load(path)
        return payload["parsed"], json.dumps({"engine": "fake", "original_text": "", "extraction": payload["parsed"]})

    def gemini(self, path, kind):
        from app.extraction.gemini import VisionExtractionError

        self.gemini_calls.append(path)
        if self.gemini_error:
            raise VisionExtractionError(self.gemini_error, "{}")
        payload = self._load(path)
        return payload["parsed"], json.dumps(payload["parsed"])


@pytest.fixture
def providers(monkeypatch):
    from app.api import image_upload

    fake = FakeProviders()
    monkeypatch.setattr(image_upload, "classify_document", fake.classify)
    monkeypatch.setattr(image_upload, "extract_ticket_ocr", fake.ocr)
    monkeypatch.setattr(image_upload, "extract_gemini_image", fake.gemini)
    return fake


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


# ------------------------------------------------------------------- helpers

def upload(client, kind, files, branch=BRANCH, selected_date=DATE):
    """files: list of (filename, bytes, content_type)."""
    response = client.post(
        f"/api/upload/{kind}s",
        files=[("files", f) for f in files],
        data={"branch": branch, "selected_date": selected_date},
    )
    return response


def wait_for_batch(client, batch_id, timeout=30.0):
    deadline = time.monotonic() + timeout
    while True:
        jobs = client.get(f"/api/upload/jobs/{batch_id}").json()["jobs"]
        if all(job["status"] not in {"queued", "processing"} for job in jobs):
            return jobs
        if time.monotonic() > deadline:
            raise AssertionError(f"batch {batch_id} did not finish: {jobs}")
        time.sleep(0.05)


def upload_and_wait(client, kind, files, timeout=30.0, **kwargs):
    response = upload(client, kind, files, **kwargs)
    assert response.status_code == 200, response.text
    body = response.json()
    jobs = wait_for_batch(client, body["batch_id"], timeout)
    return body, jobs


def query(sql, params=()):
    from app.storage import db

    with db.get_db_connection() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]

"""Wrong-upload rejection using the real Tesseract classifier on real sample images.

Skipped automatically when Tesseract is not installed/configured.
"""
import shutil

import pytest

from conftest import FIXTURES, PROJECT_ROOT, query, upload_and_wait
from app.api import image_upload

try:
    from dotenv import dotenv_values
    from app.extraction.ticket_ocr import _tesseract_module
    import os

    os.environ.setdefault("TESSERACT_CMD", dotenv_values(PROJECT_ROOT / ".env").get("TESSERACT_CMD") or "")
    _tesseract_module()
    HAVE_TESSERACT = True
except Exception:
    HAVE_TESSERACT = False

pytestmark = [pytest.mark.ocr, pytest.mark.skipif(not HAVE_TESSERACT, reason="Tesseract OCR not available")]

REAL_TICKET = (FIXTURES / "real_ticket.jpeg").read_bytes()
REAL_DOCKET = (FIXTURES / "real_docket.jpeg").read_bytes()


@pytest.fixture
def no_gemini(monkeypatch):
    def fail(*_args, **_kwargs):
        raise AssertionError("Gemini must not be called in these tests")
    monkeypatch.setattr(image_upload, "extract_gemini_image", fail)


def test_classifier_recognises_sample_images():
    tmp_ticket = shutil.copy(FIXTURES / "real_ticket.jpeg", "real_ticket.jpeg")
    tmp_docket = shutil.copy(FIXTURES / "real_docket.jpeg", "real_docket.jpeg")
    assert image_upload.classify_document(tmp_ticket)[0] == "ticket"
    assert image_upload.classify_document(tmp_docket)[0] == "docket"


def test_real_docket_uploaded_as_ticket_is_rejected(client, no_gemini):
    _, jobs = upload_and_wait(client, "ticket", [("docket.jpeg", REAL_DOCKET, "image/jpeg")], timeout=120)
    assert jobs[0]["status"] == "failed"
    assert jobs[0]["error"] == "This looks like a docket, not a ticket image"
    assert query("SELECT * FROM ticket_records") == []
    assert query("SELECT * FROM unassigned_screenshots") == []


def test_real_ticket_uploaded_as_docket_is_rejected(client, no_gemini):
    _, jobs = upload_and_wait(client, "docket", [("ticket.jpeg", REAL_TICKET, "image/jpeg")], timeout=120)
    assert jobs[0]["status"] == "failed"
    assert jobs[0]["error"] == "This looks like a ticket, not a docket image"
    assert query("SELECT * FROM docket_records") == []


def test_real_ticket_is_accepted_by_ticket_pipeline(client, no_gemini):
    _, jobs = upload_and_wait(client, "ticket", [("ticket.jpeg", REAL_TICKET, "image/jpeg")], timeout=180)
    assert jobs[0]["status"] == "done", jobs[0]
    assert jobs[0]["provider"] == "tesseract_ocr"
    # Branch/date of the sample may differ from the test's selection, so it is either
    # saved directly or parked for confirmation; either way it was not rejected.
    assert jobs[0]["message"].startswith(("Saved ticket", "Needs confirmation"))

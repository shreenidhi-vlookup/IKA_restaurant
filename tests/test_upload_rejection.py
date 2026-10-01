"""Wrong or unusable uploads must be rejected without creating records."""
import os

import pytest

from conftest import (
    BRANCH, DATE, docket_view, fake_image, query, ticket_parsed, upload, upload_and_wait,
)
from app.api import image_upload


def _records():
    return {
        "tickets": query("SELECT ticket_id FROM ticket_records"),
        "dockets": query("SELECT id FROM docket_records"),
        "unassigned": query("SELECT filename FROM unassigned_screenshots"),
    }


def _assert_nothing_saved():
    assert _records() == {"tickets": [], "dockets": [], "unassigned": []}


def test_non_image_file_rejected_for_tickets(client, providers):
    response = upload(client, "ticket", [("notes.txt", b"hello", "text/plain")])
    assert response.status_code == 200
    job = response.json()["jobs"][0]
    assert job == {"job_id": None, "filename": "notes.txt", "status": "failed", "message": "File must be an image"}
    assert os.listdir(image_upload.TICKET_DIR) == []
    assert query("SELECT * FROM upload_hashes") == []
    rows = query("SELECT status,error FROM extraction_jobs")
    assert rows == [{"status": "failed", "error": "File must be an image"}]
    assert providers.ocr_calls == []
    _assert_nothing_saved()


def test_pdf_rejected_for_dockets(client, providers):
    response = upload(client, "docket", [("docket.pdf", b"%PDF-1.4", "application/pdf")])
    assert response.json()["jobs"][0]["status"] == "failed"
    assert os.listdir(image_upload.DOCKET_DIR) == []
    assert providers.gemini_calls == []
    _assert_nothing_saved()


def test_docket_image_uploaded_as_ticket_is_rejected(client, providers):
    image = fake_image("docket", {"dockets": [docket_view()]})
    _, jobs = upload_and_wait(client, "ticket", [("docket.jpg", image, "image/jpeg")])
    assert jobs[0]["status"] == "failed"
    assert jobs[0]["message"] == "Held for review"
    assert jobs[0]["error"] == "This looks like a docket, not a ticket image"
    assert providers.ocr_calls == [], "extraction must not run on a misclassified image"
    audit = query("SELECT kind FROM upload_audits")
    assert audit == [{"kind": "ticket:classification_rejected"}]
    _assert_nothing_saved()


def test_ticket_image_uploaded_as_docket_is_rejected(client, providers):
    image = fake_image("ticket", ticket_parsed())
    _, jobs = upload_and_wait(client, "docket", [("ticket.jpg", image, "image/jpeg")])
    assert jobs[0]["status"] == "failed"
    assert jobs[0]["error"] == "This looks like a ticket, not a docket image"
    assert providers.gemini_calls == [], "Gemini must not be called for a misclassified image"
    _assert_nothing_saved()


def test_uncertain_image_is_held_for_review(client, providers):
    _, jobs = upload_and_wait(client, "ticket", [("photo.jpg", fake_image("uncertain"), "image/jpeg")])
    assert jobs[0]["status"] == "failed"
    assert jobs[0]["message"] == "Held for review"
    assert "document type is uncertain" in jobs[0]["error"]
    # Held evidence stays on disk for the operator to look at.
    assert len(os.listdir(image_upload.TICKET_DIR)) == 1
    _assert_nothing_saved()


def test_blank_docket_rejected(client, providers):
    _, jobs = upload_and_wait(client, "docket", [("blank.jpg", fake_image("docket", {}), "image/jpeg")])
    assert jobs[0]["status"] == "failed"
    assert jobs[0]["message"] == "Extraction failed"
    assert "No text or structured fields" in jobs[0]["error"]
    _assert_nothing_saved()


def test_blank_ticket_rejected(client, providers):
    _, jobs = upload_and_wait(client, "ticket", [("blank.jpg", fake_image("ticket", {}), "image/jpeg")])
    assert jobs[0]["status"] == "failed"
    assert "No text or structured fields" in jobs[0]["error"]
    _assert_nothing_saved()


def test_docket_with_no_views_rejected(client, providers):
    image = fake_image("docket", {"dockets": [], "note": "something"})
    _, jobs = upload_and_wait(client, "docket", [("d.jpg", image, "image/jpeg")])
    assert jobs[0]["status"] == "failed"
    assert "no structured docket views" in jobs[0]["error"]
    _assert_nothing_saved()


def test_gemini_failure_marks_job_failed(client, providers):
    providers.gemini_error = "quota exhausted"
    image = fake_image("docket", {"dockets": [docket_view()]})
    _, jobs = upload_and_wait(client, "docket", [("d.jpg", image, "image/jpeg")])
    assert jobs[0]["status"] == "failed"
    assert jobs[0]["provider"] == "gemini"
    assert "quota exhausted" in jobs[0]["error"]
    _assert_nothing_saved()


def test_too_many_files_rejected(client, providers):
    files = [(f"t{i}.jpg", fake_image("ticket", ticket_parsed(), nonce=str(i)), "image/jpeg")
             for i in range(image_upload.MAX_FILES + 1)]
    response = upload(client, "ticket", files)
    assert response.status_code == 400
    assert "at most 30" in response.json()["detail"]
    assert query("SELECT * FROM extraction_jobs") == []


def test_missing_branch_or_date_rejected(client, providers):
    files = [("files", ("t.jpg", fake_image("ticket", ticket_parsed()), "image/jpeg"))]
    assert client.post("/api/upload/tickets", files=files, data={"selected_date": DATE}).status_code == 422
    assert client.post("/api/upload/tickets", files=files, data={"branch": BRANCH}).status_code == 422
    assert client.post("/api/upload/tickets", data={"branch": BRANCH, "selected_date": DATE}).status_code == 422


def test_mixed_batch_handles_each_file_independently(client, providers):
    files = [
        ("good.jpg", fake_image("ticket", ticket_parsed()), "image/jpeg"),
        ("notes.txt", b"not an image", "text/plain"),
        ("docket.jpg", fake_image("docket", {"dockets": [docket_view()]}), "image/jpeg"),
    ]
    body, jobs = upload_and_wait(client, "ticket", files)
    assert body["total"] == 3
    by_name = {job["filename"]: job for job in jobs}
    assert by_name["good.jpg"]["status"] == "done"
    assert by_name["good.jpg"]["message"] == "Saved ticket 260930-12"
    assert by_name["notes.txt"]["error"] == "File must be an image"
    assert by_name["docket.jpg"]["error"] == "This looks like a docket, not a ticket image"
    assert [r["ticket_id"] for r in query("SELECT ticket_id FROM ticket_records")] == ["260930-12"]
    assert query("SELECT id FROM docket_records") == []

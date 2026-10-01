"""Ticket screenshot pipeline: save, duplicates, bulk merge, unassigned + resolve."""
import json
import os
import threading

import pytest

from conftest import BRANCH, DATE, TICKET_ID, fake_image, query, ticket_parsed, upload_and_wait
from app.api import image_upload

CHIPS = {"name": "Chips", "qty": "1", "price": "1.00", "total": "1.00", "is_void": False}
COLA = {"name": "Cola", "qty": "1", "price": "2.00", "total": "2.00", "is_void": False}
SALAD = {"name": "Salad", "qty": "1", "price": "3.00", "total": "3.00", "is_void": False}


def test_valid_ticket_is_saved_with_items(client, providers):
    _, jobs = upload_and_wait(client, "ticket", [("t.jpg", fake_image("ticket", ticket_parsed()), "image/jpeg")])
    assert jobs[0]["status"] == "done"
    assert jobs[0]["provider"] == "tesseract_ocr"

    tickets = client.get("/api/tickets", params={"branch": BRANCH, "selected_date": DATE}).json()
    assert [t["ticket_id"] for t in tickets] == [TICKET_ID]
    ticket = tickets[0]
    assert ticket["ticket_id_display"] == f"#{TICKET_ID}"
    assert ticket["user_name"] == "Alice" and ticket["department"] == "Bar" and ticket["terminal"] == "T1"
    assert json.loads(ticket["items"])[0]["name"] == "Burger (Void)"

    items = query("SELECT item,qty,total,is_void,row_tint,strikethrough_line,void_label_text FROM ticket_items")
    assert items == [{"item": "Burger (Void)", "qty": "1", "total": "10.00", "is_void": 1,
                      "row_tint": 1, "strikethrough_line": 1, "void_label_text": 1}]
    assert len(query("SELECT * FROM upload_hashes WHERE kind='ticket'")) == 1


def test_ticket_list_is_filtered_by_branch_and_day(client, providers):
    upload_and_wait(client, "ticket", [("t.jpg", fake_image("ticket", ticket_parsed()), "image/jpeg")])
    assert client.get("/api/tickets", params={"branch": "York", "selected_date": DATE}).json() == []
    assert client.get("/api/tickets", params={"branch": BRANCH, "selected_date": "2026-10-01"}).json() == []


def test_duplicate_upload_is_skipped(client, providers):
    image = fake_image("ticket", ticket_parsed())
    upload_and_wait(client, "ticket", [("t.jpg", image, "image/jpeg")])
    _, jobs = upload_and_wait(client, "ticket", [("t-again.jpg", image, "image/jpeg")])
    assert jobs[0]["status"] == "done"
    assert jobs[0]["message"] == "Duplicate, skipped"
    assert len(os.listdir(image_upload.TICKET_DIR)) == 1
    assert len(providers.ocr_calls) == 1
    assert len(query("SELECT * FROM ticket_records")) == 1


def test_duplicate_within_one_batch_is_skipped(client, providers):
    image = fake_image("ticket", ticket_parsed())
    _, jobs = upload_and_wait(client, "ticket", [("a.jpg", image, "image/jpeg"), ("b.jpg", image, "image/jpeg")])
    assert sorted(job["message"] for job in jobs) == ["Duplicate, skipped", "Saved ticket 260930-12"]
    assert len(os.listdir(image_upload.TICKET_DIR)) == 1


def test_screenshots_of_one_ticket_merge_without_duplicate_rows(client, providers):
    """Two overlapping screenshots of a long ticket, uploaded one after the other."""
    top = fake_image("ticket", ticket_parsed(items=[CHIPS, COLA], ticket_total="6.00"))
    bottom = fake_image("ticket", ticket_parsed(items=[COLA, SALAD], ticket_total="6.00"))
    upload_and_wait(client, "ticket", [("top.jpg", top, "image/jpeg")])
    upload_and_wait(client, "ticket", [("bottom.jpg", bottom, "image/jpeg")])

    record = query("SELECT * FROM ticket_records")[0]
    assert [i["name"] for i in json.loads(record["items"])] == ["Chips", "Cola", "Salad"]
    assert len(json.loads(record["screenshot_filenames"])) == 2
    assert json.loads(record["review_flags"]) == []
    assert [r["item"] for r in query("SELECT item FROM ticket_items ORDER BY id")] == ["Chips", "Cola", "Salad"]


def test_bulk_upload_of_one_ticket_in_a_single_batch(client, providers, monkeypatch):
    """Same as above but both screenshots in one batch, processed by parallel workers.

    A barrier makes both workers reach the save at the same time, which is what happens
    when real OCR on two screenshots finishes together."""
    barrier = threading.Barrier(2, timeout=10)
    real_upsert = image_upload.upsert_ticket_record

    def synchronised_upsert(ticket):
        barrier.wait()
        return real_upsert(ticket)

    monkeypatch.setattr(image_upload, "upsert_ticket_record", synchronised_upsert)
    top = fake_image("ticket", ticket_parsed(items=[CHIPS, COLA], ticket_total="6.00"))
    bottom = fake_image("ticket", ticket_parsed(items=[COLA, SALAD], ticket_total="6.00"))
    _, jobs = upload_and_wait(client, "ticket", [("top.jpg", top, "image/jpeg"), ("bottom.jpg", bottom, "image/jpeg")])
    assert all(job["status"] == "done" for job in jobs)
    record = query("SELECT * FROM ticket_records")[0]
    assert [i["name"] for i in json.loads(record["items"])] == ["Chips", "Cola", "Salad"]
    assert len(json.loads(record["screenshot_filenames"])) == 2


def test_bulk_upload_of_many_different_tickets(client, providers):
    files = [(f"t{n}.jpg", fake_image("ticket", ticket_parsed(ticket_id=f"260930-{n}")), "image/jpeg") for n in range(1, 11)]
    _, jobs = upload_and_wait(client, "ticket", files)
    assert [job["status"] for job in jobs] == ["done"] * 10
    ids = sorted(r["ticket_id"] for r in query("SELECT ticket_id FROM ticket_records"))
    assert ids == sorted(f"260930-{n}" for n in range(1, 11))


def test_unreadable_ticket_id_goes_to_unassigned_then_resolves(client, providers):
    image = fake_image("ticket", ticket_parsed(ticket_id="26O930-12"))
    _, jobs = upload_and_wait(client, "ticket", [("t.jpg", image, "image/jpeg")])
    assert jobs[0]["status"] == "done"
    assert jobs[0]["message"].startswith("Needs confirmation: Ticket ID unreadable")
    assert query("SELECT * FROM ticket_records") == []

    pending = client.get("/api/tickets/unassigned", params={"branch": BRANCH, "selected_date": DATE}).json()
    assert len(pending) == 1
    filename = pending[0]["filename"]

    bad = client.post("/api/tickets/resolve", data={"filename": filename, "branch": BRANCH, "selected_date": DATE, "ticket_id": "abc"})
    assert bad.status_code == 400

    ok = client.post("/api/tickets/resolve", data={"filename": filename, "branch": BRANCH, "selected_date": DATE, "ticket_id": "#260930-12"})
    assert ok.status_code == 200, ok.text
    assert ok.json() == {"ticket_id": TICKET_ID, "status": "saved", "warnings": []}
    assert client.get("/api/tickets/unassigned", params={"branch": BRANCH, "selected_date": DATE}).json() == []
    assert [r["ticket_id"] for r in query("SELECT ticket_id FROM ticket_records")] == [TICKET_ID]


def test_branch_mismatch_requires_confirmation(client, providers):
    image = fake_image("ticket", ticket_parsed(branch="Manchester"))
    _, jobs = upload_and_wait(client, "ticket", [("t.jpg", image, "image/jpeg")])
    assert "Ticket branch mismatch: image says Manchester" in jobs[0]["message"]
    filename = query("SELECT filename FROM unassigned_screenshots")[0]["filename"]

    form = {"filename": filename, "branch": BRANCH, "selected_date": DATE}
    needs_confirm = client.post("/api/tickets/resolve", data=form)
    assert needs_confirm.status_code == 409
    assert needs_confirm.json()["detail"]["warnings"] == ["Ticket branch differs from selected branch"]
    assert query("SELECT * FROM ticket_records") == []

    confirmed = client.post("/api/tickets/resolve", data={**form, "confirm_mismatch": "true"})
    assert confirmed.status_code == 200
    assert confirmed.json()["warnings"] == ["Ticket branch differs from selected branch"]
    assert len(query("SELECT * FROM ticket_records")) == 1


def test_ticket_from_another_day_goes_to_unassigned(client, providers):
    image = fake_image("ticket", ticket_parsed(ticket_id="260929-5"))
    _, jobs = upload_and_wait(client, "ticket", [("t.jpg", image, "image/jpeg")])
    assert "Ticket date mismatch: ID belongs to 2026-09-29" in jobs[0]["message"]
    assert query("SELECT * FROM ticket_records") == []


def test_resolve_unknown_screenshot_is_404(client, providers):
    response = client.post("/api/tickets/resolve", data={"filename": "nope.jpg", "branch": BRANCH, "selected_date": DATE})
    assert response.status_code == 404


def test_uploaded_image_is_served_with_cache_headers(client, providers):
    upload_and_wait(client, "ticket", [("t.jpg", fake_image("ticket", ticket_parsed()), "image/jpeg")])
    uploads = client.get("/api/uploads", params={"branch": BRANCH, "selected_date": DATE}).json()
    assert len(uploads) == 1 and uploads[0]["kind"] == "ticket"
    image = client.get(uploads[0]["url"])
    assert image.status_code == 200
    assert image.headers["cache-control"] == "public, max-age=31536000, immutable"

"""Deleting an uploaded image removes its record, file, hash and audit trail."""
import json
import os

from conftest import BRANCH, DATE, docket_view, fake_image, query, ticket_parsed, upload_and_wait
from app.api import image_upload
from test_tickets import CHIPS, COLA, SALAD


def _stored(kind):
    return query("SELECT stored_filename FROM extraction_jobs WHERE kind=?", (kind,))[0]["stored_filename"]


def test_delete_ticket_upload_removes_everything(client, providers):
    image = fake_image("ticket", ticket_parsed())
    upload_and_wait(client, "ticket", [("t.jpg", image, "image/jpeg")])
    filename = _stored("ticket")

    response = client.delete(f"/api/uploads/ticket/{filename}")
    assert response.status_code == 200
    assert response.json() == {"deleted": True, "filename": filename}
    assert os.listdir(image_upload.TICKET_DIR) == []
    assert query("SELECT * FROM ticket_records") == []
    assert query("SELECT * FROM ticket_items") == []
    assert query("SELECT * FROM upload_hashes") == []
    assert query("SELECT * FROM extraction_jobs") == []
    assert [r["kind"] for r in query("SELECT kind FROM upload_audits")] == ["image:manual_delete"]

    # The same image can be uploaded again afterwards (not treated as a duplicate).
    _, jobs = upload_and_wait(client, "ticket", [("t.jpg", image, "image/jpeg")])
    assert jobs[0]["message"] == "Saved ticket 260930-12"


def test_delete_one_screenshot_keeps_the_rest_of_the_ticket(client, providers):
    upload_and_wait(client, "ticket", [("top.jpg", fake_image("ticket", ticket_parsed(items=[CHIPS, COLA])), "image/jpeg")])
    top = _stored("ticket")
    upload_and_wait(client, "ticket", [("bottom.jpg", fake_image("ticket", ticket_parsed(items=[COLA, SALAD])), "image/jpeg")])

    assert client.delete(f"/api/uploads/ticket/{top}").status_code == 200
    record = query("SELECT * FROM ticket_records")[0]
    assert top not in json.loads(record["screenshot_filenames"])
    assert [i["name"] for i in json.loads(record["items"])] == ["Cola", "Salad"]
    assert [r["item"] for r in query("SELECT item FROM ticket_items ORDER BY id")] == ["Cola", "Salad"]


def test_delete_docket_upload(client, providers):
    upload_and_wait(client, "docket", [("d.jpg", fake_image("docket", {"dockets": [docket_view()]}), "image/jpeg")])
    filename = _stored("docket")
    assert client.delete(f"/api/uploads/docket/{filename}").status_code == 200
    assert query("SELECT * FROM docket_records") == []
    assert os.listdir(image_upload.DOCKET_DIR) == []
    assert client.get("/api/dockets", params={"branch": BRANCH, "selected_date": DATE}).json() == []


def test_delete_rejects_bad_kind_and_unsafe_names(client, providers):
    assert client.delete("/api/uploads/invoice/a.jpg").status_code == 400
    assert client.delete("/api/uploads/ticket/a%20b.jpg").status_code == 400
    assert client.delete("/api/uploads/ticket/..%5Cdata%5Ctil_system.db").status_code == 400
    if not os.getenv("DATABASE_URL"):
        assert os.path.isfile("data/til_system.db")


def test_delete_unknown_upload_is_404(client, providers):
    assert client.delete("/api/uploads/ticket/ticket-missing.jpg").status_code == 404


def test_delete_while_extraction_pending_is_409(client, providers):
    with image_upload.get_db_connection() as conn:
        conn.execute("""INSERT INTO extraction_jobs(job_id,batch_id,kind,original_filename,stored_filename,file_hash,branch,selected_date,status)
            VALUES('j1','b1','ticket','t.jpg','ticket-pending.jpg','h',?,?,'processing')""", (BRANCH, DATE))
        conn.commit()
    assert client.delete("/api/uploads/ticket/ticket-pending.jpg").status_code == 409
    assert len(query("SELECT * FROM extraction_jobs")) == 1

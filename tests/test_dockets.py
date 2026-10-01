"""Docket pipeline: save, multi-view images, partial fields, merging re-photographs."""
import json

from conftest import BRANCH, DATE, docket_view, fake_image, query, upload_and_wait


def test_valid_docket_is_saved(client, providers):
    _, jobs = upload_and_wait(client, "docket", [("d.jpg", fake_image("docket", {"dockets": [docket_view()]}), "image/jpeg")])
    assert jobs[0]["status"] == "done"
    assert jobs[0]["message"] == "Saved 1 docket view(s)"
    assert jobs[0]["provider"] == "gemini"

    dockets = client.get("/api/dockets", params={"branch": BRANCH, "selected_date": DATE}).json()
    assert len(dockets) == 1
    docket = dockets[0]
    assert docket["docket_order_no"] == "12"
    assert docket["staff_name"] == "Alice"
    assert docket["discrepancy_type"] == "void"
    assert docket["item"] == "Burger"
    assert docket["review_required"] == 0
    assert json.loads(docket["item_lines"])[0]["name"] == "Burger"


def test_order_number_is_reduced_to_trailing_digits(client, providers):
    upload_and_wait(client, "docket", [("d.jpg", fake_image("docket", {"dockets": [docket_view(order="Order No: 0034")]}), "image/jpeg")])
    assert query("SELECT docket_order_no FROM docket_records") == [{"docket_order_no": "0034"}]


def test_one_image_with_two_dockets_creates_two_records(client, providers):
    views = [docket_view(order="12"), docket_view(order="13", items=[{"name": "Cola", "quantity": 1, "is_void": True, "marker_type": "void"}])]
    _, jobs = upload_and_wait(client, "docket", [("two.jpg", fake_image("docket", {"dockets": views}), "image/jpeg")])
    assert jobs[0]["message"] == "Saved 2 docket view(s)"
    rows = query("SELECT docket_order_no,multiple_dockets FROM docket_records ORDER BY docket_order_no")
    assert rows == [{"docket_order_no": "12", "multiple_dockets": 1}, {"docket_order_no": "13", "multiple_dockets": 1}]


def test_partially_cropped_docket_needs_review(client, providers):
    view = docket_view(partial_fields=["table", "covers"])
    upload_and_wait(client, "docket", [("d.jpg", fake_image("docket", {"dockets": [view]}), "image/jpeg")])
    row = query("SELECT review_required,review_reason,partial_fields FROM docket_records")[0]
    assert row["review_required"] == 1
    assert row["review_reason"] == "Partly cropped fields: table, covers"
    assert json.loads(row["partial_fields"]) == ["table", "covers"]


def test_second_photo_of_same_docket_merges_into_one_record(client, providers):
    upload_and_wait(client, "docket", [("a.jpg", fake_image("docket", {"dockets": [docket_view()]}, nonce="a"), "image/jpeg")])
    upload_and_wait(client, "docket", [("b.jpg", fake_image("docket", {"dockets": [docket_view()]}, nonce="b"), "image/jpeg")])
    rows = query("SELECT image_filenames,field_conflicts,item_lines FROM docket_records")
    assert len(rows) == 1
    assert len(json.loads(rows[0]["image_filenames"])) == 2
    assert json.loads(rows[0]["field_conflicts"]) == []
    assert [i["name"] for i in json.loads(rows[0]["item_lines"])] == ["Burger"]


def test_conflicting_readings_of_same_docket_flag_review(client, providers):
    upload_and_wait(client, "docket", [("a.jpg", fake_image("docket", {"dockets": [docket_view()]}, nonce="a"), "image/jpeg")])
    upload_and_wait(client, "docket", [("b.jpg", fake_image("docket", {"dockets": [docket_view(staff_name="Bob")]}, nonce="b"), "image/jpeg")])
    row = query("SELECT review_required,review_reason,field_conflicts FROM docket_records")[0]
    assert row["review_required"] == 1
    assert row["review_reason"] == "Conflicting readings: staff_name"
    assert json.loads(row["field_conflicts"]) == [{"field": "staff_name", "values": ["Alice", "Bob"]}]


def test_dockets_endpoint_only_returns_selected_day_uploads(client, providers):
    upload_and_wait(client, "docket", [("d.jpg", fake_image("docket", {"dockets": [docket_view()]}), "image/jpeg")])
    assert client.get("/api/dockets", params={"branch": BRANCH, "selected_date": "2026-10-01"}).json() == []
    assert client.get("/api/dockets", params={"branch": "York", "selected_date": DATE}).json() == []

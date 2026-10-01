"""TIL CSV import validation and void/cancel verification against tickets + dockets."""
from conftest import BRANCH, DATE, docket_view, fake_image, query, ticket_parsed, upload_and_wait

HEADER = "Date,Product Name,Quantity,User,Department,Till,Category,Group,Sales Value,Void,Cancel"
VOID_ROW = f"{DATE},Burger,1,Alice,Bar,T1,Food,Mains,10.00,1,0"
PLAIN_ROW = f"{DATE},Cola,2,Alice,Bar,T1,Drinks,Soft,4.00,0,0"


def post_csv(client, body, filename="til.csv", branch=BRANCH, selected_date=DATE, **extra):
    return client.post(
        "/api/csv",
        files={"file": (filename, body.encode(), "text/csv")},
        data={"branch": branch, "selected_date": selected_date, **extra},
    )


def test_csv_import_saves_rows(client):
    body = f"TIL export for Leeds\n\n{HEADER}\n{VOID_ROW}\n{PLAIN_ROW}\n"
    response = post_csv(client, body)
    assert response.status_code == 200, response.text
    assert response.json() == {"saved_rows": 2, "branch": BRANCH, "date": DATE, "csv_dates": [DATE], "promotions_in_file": False}
    rows = query("SELECT product,quantity,sales_value,void_count FROM csv_rows ORDER BY id")
    assert rows == [{"product": "Burger", "quantity": 1.0, "sales_value": 10.0, "void_count": 1.0},
                    {"product": "Cola", "quantity": 2.0, "sales_value": 4.0, "void_count": 0.0}]


def test_reimport_replaces_previous_rows(client):
    post_csv(client, f"{HEADER}\n{VOID_ROW}\n{PLAIN_ROW}\n")
    post_csv(client, f"{HEADER}\n{PLAIN_ROW}\n")
    assert [r["product"] for r in query("SELECT product FROM csv_rows")] == ["Cola"]


def test_non_csv_file_rejected(client):
    response = post_csv(client, f"{HEADER}\n{VOID_ROW}\n", filename="til.xlsx")
    assert response.status_code == 400
    assert response.json()["detail"] == "Upload one CSV file"


def test_bad_date_rejected(client):
    assert post_csv(client, f"{HEADER}\n{VOID_ROW}\n", selected_date="30/09/2026").status_code == 400


def test_blank_branch_rejected(client):
    assert post_csv(client, f"{HEADER}\n{VOID_ROW}\n", branch="   ").status_code == 400


def test_csv_without_product_header_rejected(client):
    response = post_csv(client, "a,b,c\n1,2,3\n")
    assert response.status_code == 400
    assert "Product Name" in response.json()["detail"]
    assert query("SELECT * FROM csv_rows") == []


def test_csv_with_header_but_no_rows_rejected(client):
    assert post_csv(client, f"{HEADER}\n").status_code == 400


def test_csv_date_mismatch_needs_confirmation(client):
    other_day = "2026-09-29,Burger,1,Alice,Bar,T1,Food,Mains,10.00,1,0"
    response = post_csv(client, f"{HEADER}\n{other_day}\n")
    assert response.status_code == 200
    assert response.json()["confirmation_required"] is True
    assert query("SELECT * FROM csv_rows") == []

    confirmed = post_csv(client, f"{HEADER}\n{other_day}\n", confirm_date_mismatch="true")
    assert confirmed.json()["saved_rows"] == 1


def test_promotion_column_detected(client):
    body = f"{HEADER},Promotion\n{DATE},Burger,1,Alice,Bar,T1,Food,Mains,10.00,0,0,1\n"
    assert post_csv(client, body).json()["promotions_in_file"] is True
    assert query("SELECT promotion_count FROM csv_rows") == [{"promotion_count": 1.0}]


def test_verification_dates_listing(client):
    post_csv(client, f"{HEADER}\n{VOID_ROW}\n{PLAIN_ROW}\n")
    body = client.get("/api/verification/dates", params={"branch": BRANCH}).json()
    assert body == {"branch": BRANCH, "dates": [{"date": DATE, "filename": "til.csv", "item_rows": 2, "flagged_rows": 1}]}


def _void_status(client):
    report = client.get("/api/verification", params={"branch": BRANCH, "selected_date": DATE}).json()
    burger = next(row for row in report["rows"] if row["product"] == "Burger")
    return report, burger


def test_void_pending_without_evidence(client):
    post_csv(client, f"{HEADER}\n{VOID_ROW}\n{PLAIN_ROW}\n")
    report, burger = _void_status(client)
    assert report["has_import"] is True
    assert burger["matches"]["void"]["status"] == "pending"
    assert report["summary"]["void"] == {"flagged_rows": 1, "amount": 10.0, "verified": 0, "total": 1}
    assert report["summary"]["status"]["label"] == "0 of 1 verified"


def test_void_verified_by_matching_ticket_and_docket(client, providers):
    post_csv(client, f"{HEADER}\n{VOID_ROW}\n{PLAIN_ROW}\n")
    upload_and_wait(client, "ticket", [("t.jpg", fake_image("ticket", ticket_parsed()), "image/jpeg")])
    upload_and_wait(client, "docket", [("d.jpg", fake_image("docket", {"dockets": [docket_view()]}), "image/jpeg")])
    report, burger = _void_status(client)
    assert burger["matches"]["void"] == {"status": "verified", "verified": 1, "total": 1}
    assert burger["row_status"] == "verified"
    assert report["summary"]["status"]["label"] == "Verified"


def test_void_needs_review_when_ticket_item_is_not_voided(client, providers):
    post_csv(client, f"{HEADER}\n{VOID_ROW}\n")
    not_void = [{"name": "Burger", "qty": "1", "price": "10.00", "total": "10.00", "is_void": False}]
    upload_and_wait(client, "ticket", [("t.jpg", fake_image("ticket", ticket_parsed(items=not_void)), "image/jpeg")])
    _, burger = _void_status(client)
    assert burger["matches"]["void"]["status"] == "needs_review"


def test_void_needs_review_when_docket_staff_disagrees(client, providers):
    post_csv(client, f"{HEADER}\n{VOID_ROW}\n")
    upload_and_wait(client, "ticket", [("t.jpg", fake_image("ticket", ticket_parsed()), "image/jpeg")])
    upload_and_wait(client, "docket", [("d.jpg", fake_image("docket", {"dockets": [docket_view(staff_name="Bob")]}), "image/jpeg")])
    _, burger = _void_status(client)
    assert burger["matches"]["void"]["status"] == "needs_review"


def test_ticket_only_evidence_is_partial(client, providers):
    post_csv(client, f"{HEADER}\n{VOID_ROW}\n")
    upload_and_wait(client, "ticket", [("t.jpg", fake_image("ticket", ticket_parsed()), "image/jpeg")])
    _, burger = _void_status(client)
    assert burger["matches"]["void"]["status"] == "partial"


def test_other_branch_evidence_is_ignored(client, providers):
    post_csv(client, f"{HEADER}\n{VOID_ROW}\n")
    upload_and_wait(client, "ticket", [("t.jpg", fake_image("ticket", ticket_parsed(branch=None)), "image/jpeg")], branch="York")
    _, burger = _void_status(client)
    assert burger["matches"]["void"]["status"] == "pending"

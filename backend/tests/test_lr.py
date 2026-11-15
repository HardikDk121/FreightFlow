import io

from pypdf import PdfReader

from tests.conftest import add_staff, bearer, register
from tests.test_lr_print import SAMPLE

NEW_LR = {k: v for k, v in SAMPLE.items() if k != "lr_number"}


def _create(client, tokens, **changes):
    response = client.post("/lrs", json={**NEW_LR, **changes}, headers=bearer(tokens))
    assert response.status_code == 201, response.text
    return response.json()


def test_numbers_follow_the_series_set_by_the_admin(client, admin):
    h = bearer(admin)
    assert client.get("/lrs/defaults", headers=h).json()["next_lr_number"] == "LR-1"
    settings = client.patch(
        "/lrs/settings",
        json={"prefix": "rjt", "next_number": 422692, "from_city": "RAJKOT", "default_st_charges": "35"},
        headers=h,
    )
    assert settings.status_code == 200 and settings.json()["prefix"] == "RJT"
    defaults = client.get("/lrs/defaults", headers=h).json()
    assert defaults == {"next_lr_number": "RJT-422692", "from_city": "RAJKOT", "st_charges": "35.00"}

    first, second = _create(client, admin), _create(client, admin)
    assert (first["lr_number"], second["lr_number"]) == ("RJT-422692", "RJT-422693")
    assert first["status"] == "confirmed" and first["total"] == "35.00"
    # moving the series back onto used numbers is refused
    back = client.patch("/lrs/settings", json={"next_number": 422693}, headers=h)
    assert back.status_code == 409


def test_a_failed_save_does_not_use_up_a_number(client, admin):
    h = bearer(admin)
    assert client.post("/lrs", json={**NEW_LR, "consignor_gstin": "bad"}, headers=h).status_code == 422
    assert _create(client, admin)["lr_number"] == "LR-1"


def test_saved_lr_prints_with_its_number(client, admin):
    lr = _create(client, admin)
    pdf = client.get(f"/lrs/{lr['id']}/pdf", headers=bearer(admin))
    assert pdf.status_code == 200
    text = PdfReader(io.BytesIO(pdf.content)).pages[0].extract_text()
    assert "LR-1" in text and "RANGOLI LAMINATE" in text


def test_cancel_keeps_the_record_and_blocks_printing(client, admin):
    clerk = add_staff(client, admin, "clerk@shree.example", "clerk")
    lr = _create(client, clerk)
    assert client.post(f"/lrs/{lr['id']}/cancel", json={"reason": "typo"}, headers=bearer(clerk)).status_code == 403
    cancelled = client.post(f"/lrs/{lr['id']}/cancel", json={"reason": "Wrong consignee"}, headers=bearer(admin))
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["cancel_reason"] == "Wrong consignee"
    assert client.post(f"/lrs/{lr['id']}/cancel", json={"reason": "again"}, headers=bearer(admin)).status_code == 409
    assert client.get(f"/lrs/{lr['id']}/pdf", headers=bearer(admin)).status_code == 409
    # the number is not reused
    assert _create(client, clerk)["lr_number"] == "LR-2"
    assert [x["lr_number"] for x in client.get("/lrs", headers=bearer(admin)).json()] == ["LR-2", "LR-1"]


def test_suggestions_come_from_the_consignors_last_lr(client, admin):
    h = bearer(admin)
    empty = client.get("/lrs/suggestions", params={"consignor_name": "Rangoli Laminate"}, headers=h).json()
    assert all(value is None for value in empty.values())
    _create(client, admin, freight_by="Paid", packages=5)
    _create(client, admin, freight_by="TBB", packages=7, goods_description="Sheets")
    by_name = client.get("/lrs/suggestions", params={"consignor_name": "rangoli laminate "}, headers=h).json()
    assert by_name == {
        "freight_by": "TBB",
        "packages": 7,
        "goods_description": "Sheets",
        "consignor_gstin": "24AABCR4141H1ZQ",
        "item_type_id": None,
    }
    by_gstin = client.get("/lrs/suggestions", params={"consignor_gstin": "24aabcr4141h1zq"}, headers=h).json()
    assert by_gstin["packages"] == 7


def test_search_and_roles(client, admin):
    dispatcher = add_staff(client, admin, "d@shree.example", "dispatcher")
    assert client.post("/lrs", json=NEW_LR, headers=bearer(dispatcher)).status_code == 403
    assert client.patch("/lrs/settings", json={"prefix": "X"}, headers=bearer(dispatcher)).status_code == 403
    _create(client, admin)
    _create(client, admin, consignor_name="Monal Laminate Pvt Ltd")
    found = client.get("/lrs", params={"q": "monal"}, headers=bearer(dispatcher)).json()
    assert [x["consignor_name"] for x in found] == ["Monal Laminate Pvt Ltd"]


def test_lrs_are_private_to_each_company(client, admin):
    lr = _create(client, admin)
    other = register(client, "Other Transport", "o@o.example")
    assert client.get("/lrs", headers=bearer(other)).json() == []
    assert client.get(f"/lrs/{lr['id']}", headers=bearer(other)).status_code == 404
    assert client.get(f"/lrs/{lr['id']}/pdf", headers=bearer(other)).status_code == 404
    # each company has its own series
    assert _create(client, other)["lr_number"] == "LR-1"

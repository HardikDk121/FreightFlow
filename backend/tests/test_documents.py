import io

from pypdf import PdfReader

from tests.conftest import bearer
from tests.test_dispatch import _lr, _truck
from tests.test_lr import _create

HEADER = {
    "name": "Sharma Logistics",
    "tagline": "Fleet owners & transport contractors",
    "address": "Pankaj Oil Mill Compound Godown No.D.1.2 B/H\nShri Nath Cargo Old Morvi Road Rajkot,\nOffice No 9374344718, Rajkot",
    "gstin": "24CPAPS7855E2ZO",
    "phone": "9327410932",
}


def _pages(response) -> list[str]:
    assert response.status_code == 200, response.text
    return [page.extract_text() for page in PdfReader(io.BytesIO(response.content)).pages]


def test_lr_prints_four_labelled_copies_with_the_companys_own_header(client, admin):
    h = bearer(admin)
    assert client.patch("/company", json=HEADER, headers=h).status_code == 200
    lr = _create(client, admin)

    pages = _pages(client.get(f"/lrs/{lr['id']}/pdf", headers=h))
    assert len(pages) == 4
    for page, label in zip(pages, ("CONSIGNEE COPY", "OFFICE COPY", "DRIVER COPY 1", "DRIVER COPY 2")):
        assert label in page and lr["lr_number"] in page
        for text in ("SHARMA LOGISTICS", "FLEET OWNERS & TRANSPORT CONTRACTORS", "GSTIN: 24CPAPS7855E2ZO",
                     "Contact No: 9327410932", "SHRI NATH CARGO OLD MORVI ROAD RAJKOT,"):
            assert text in page, text

    driver = _pages(client.get(f"/lrs/{lr['id']}/pdf", params={"copy": "driver1"}, headers=h))
    assert len(driver) == 1 and "DRIVER COPY 1" in driver[0] and "OFFICE COPY" not in driver[0]
    assert client.get(f"/lrs/{lr['id']}/pdf", params={"copy": "spare"}, headers=h).status_code == 422


def test_company_address_must_fit_the_header(client, admin):
    h = bearer(admin)
    assert client.patch("/company", json={"address": "1\n2\n3\n4"}, headers=h).status_code == 422
    assert client.patch("/company", json={"address": "x" * 49}, headers=h).status_code == 422
    assert client.patch("/company", json={"phone": "12"}, headers=h).status_code == 422
    ok = client.patch("/company", json={"address": " Line one \n\n Line two "}, headers=h)
    assert ok.json()["address"] == "Line one\nLine two"


def test_load_sheet_lists_the_truck_and_what_to_collect(client, admin):
    h = bearer(admin)
    truck = _truck(client, h)
    to_pay = _lr(client, h, packages=6, st_charges="35")
    paid = _lr(client, h, packages=4, freight_by="Paid", consignee_name="Kaveri Traders")
    trip = client.post(
        "/trips",
        json={
            "truck_id": truck,
            "destination": "Surat",
            "driver_name": "Ramesh",
            "lines": [{"lr_id": to_pay["id"], "packages": 2}, {"lr_id": paid["id"], "packages": 4}],
        },
        headers=h,
    ).json()
    text = _pages(client.get(f"/trips/{trip['id']}/load-sheet.pdf", headers=h))[0]
    for part in ("LOAD SHEET", "SHREE TRANSPORT", "GJ03CW0620 to SURAT", to_pay["lr_number"], "Kaveri Traders",
                 "Rs 35.00", "2 LRs", "Driver: Ramesh", "Page 1 of 1"):
        assert part in text, part

    # the rest of the to-pay LR goes on a second truck, which collects nothing
    second = client.post(
        "/trips",
        json={"truck_id": _truck(client, h, "GJ03AB0001"), "destination": "Surat", "lines": [{"lr_id": to_pay["id"], "packages": 4}]},
        headers=h,
    ).json()
    assert "Rs 35.00" not in _pages(client.get(f"/trips/{second['id']}/load-sheet.pdf", headers=h))[0]


def test_register_report_paginates_and_totals(client, admin):
    h = bearer(admin)
    for _ in range(60):
        _lr(client, h, packages=2, st_charges="10")
    cancelled = _lr(client, h, packages=9)
    client.post(f"/lrs/{cancelled['id']}/cancel", json={"reason": "test"}, headers=h)
    day = cancelled["lr_date"]
    pages = _pages(client.get("/lrs/register.pdf", params={"date_from": day, "date_to": day}, headers=h))
    assert len(pages) > 1
    assert f"Page 1 of {len(pages)}" in pages[0] and "LR No" in pages[1]
    assert "60 LRs" in pages[-1] and "600.00" in pages[-1] and "CANCELLED" in pages[-1]
    backwards = client.get("/lrs/register.pdf", params={"date_from": "2026-02-01", "date_to": "2026-01-01"}, headers=h)
    assert backwards.status_code == 409


def test_party_autocomplete(client, admin):
    h = bearer(admin)
    _create(client, admin)
    client.post("/parties", json={"name": "Jalpa Mills", "gstin": "24AAACJ1111K1Z2"}, headers=h)
    consignees = client.get("/lrs/parties", params={"q": "jal", "role": "consignee"}, headers=h).json()
    assert consignees == [
        {"name": "Jalaram Enterprise", "gstin": "22AWCPP8803A1Z0", "city": "Raipur"},
        {"name": "JALPA MILLS", "gstin": "24AAACJ1111K1Z2", "city": None},
    ]
    consignors = client.get("/lrs/parties", params={"q": "rang", "role": "consignor"}, headers=h).json()
    assert consignors == [{"name": "Rangoli Laminate", "gstin": "24AABCR4141H1ZQ", "city": None}]
    assert client.get("/lrs/parties", params={"q": "j", "role": "consignee"}, headers=h).status_code == 422

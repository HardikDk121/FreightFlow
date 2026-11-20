import datetime as dt

from app.clock import today
from tests.conftest import add_staff, bearer, register
from tests.test_dispatch import _lr, _truck


def _receipt(client, tokens, *lrs, phone="9327410932"):
    response = client.post("/receipts", json={"lr_ids": [lr["id"] for lr in lrs], "payer_phone": phone}, headers=bearer(tokens))
    assert response.status_code == 201, response.text
    return response.json()


def _visit(client, tokens, receipt, outcome, **payment):
    body = {"outcome": outcome}
    if payment:
        body["payment"] = payment
    return client.post(f"/receipts/{receipt['id']}/visits", json=body, headers=bearer(tokens))


def test_an_lr_account_lists_what_was_collected_against_it(client, admin):
    lr = _lr(client, bearer(admin), rate="9", freight="900", st_charges="100", freight_by="Paid")
    account = client.get(f"/lrs/{lr['id']}/account", headers=bearer(admin)).json()
    assert (account["total"], account["paid"], account["balance"], account["payer"]) == ("1000.00", "0", "1000.00", "Rangoli Laminate")

    receipt = _receipt(client, admin, lr)
    assert _visit(client, admin, receipt, "part_paid", method="upi", amount="400", utr="432112345678").status_code == 201
    account = client.get(f"/lrs/{lr['id']}/account", headers=bearer(admin)).json()
    assert (account["paid"], account["balance"]) == ("400.00", "600.00")
    assert [(p["amount"], p["method"], p["status"], p["reference"], p["receipt_number"]) for p in account["payments"]] == [
        ("400.00", "upi", "pending", "432112345678", "MR-1")
    ]
    # money has come in, so the LR can no longer be cancelled
    assert client.post(f"/lrs/{lr['id']}/cancel", json={"reason": "x"}, headers=bearer(admin)).status_code == 409


def test_who_owes_and_when_it_falls_due(client, admin):
    h = bearer(admin)
    account = lambda lr: client.get(f"/lrs/{lr['id']}/account", headers=h).json()
    paid_at_booking = _lr(client, h, days_ago=3, st_charges="100", freight_by="Paid")
    billed_recent = _lr(client, h, days_ago=10, st_charges="100", freight_by="TBB")
    billed_old = _lr(client, h, days_ago=45, st_charges="100", freight_by="TBB")
    to_pay = _lr(client, h, days_ago=20, st_charges="100", freight_by="ToPay", packages=2)

    assert (account(paid_at_booking)["due_on"], account(paid_at_booking)["overdue"]) == (paid_at_booking["lr_date"], True)
    assert account(billed_recent)["overdue"] is False and account(billed_old)["overdue"] is True
    assert account(billed_old)["due_on"] == str(today() - dt.timedelta(days=15))
    # the consignee pays a to-pay LR, and nothing is due until the goods are delivered
    assert (account(to_pay)["payer"], account(to_pay)["due_on"], account(to_pay)["overdue"]) == ("Jalaram Enterprise", None, False)
    trip = client.post(
        "/trips", json={"truck_id": _truck(client, h), "stops": ["Surat"], "lines": [{"lr_id": to_pay["id"], "packages": 2}]}, headers=h
    ).json()
    client.post(f"/trips/{trip['id']}/lines/{trip['lines'][0]['id']}/deliver", headers=h)
    assert account(to_pay)["due_on"] == str(today())


def test_receivables_by_party_and_roles(client, admin):
    h = bearer(admin)
    _lr(client, h, days_ago=45, st_charges="500", freight_by="TBB")
    half = _lr(client, h, days_ago=2, st_charges="300", freight_by="TBB")
    _lr(client, h, days_ago=1, st_charges="200", freight_by="TBB", consignor_name="Monal Laminate", consignor_gstin=None)
    _lr(client, h, st_charges="0")  # nothing to collect
    _visit(client, admin, _receipt(client, admin, half), "part_paid", method="cash", amount="100")

    owed = client.get("/receivables", headers=h).json()
    assert (owed["outstanding"], owed["overdue"]) == ("900.00", "500.00")
    assert [(p["party"], p["lr_count"], p["outstanding"], p["overdue"]) for p in owed["parties"]] == [
        ("Rangoli Laminate", 2, "700.00", "500.00"),
        ("Monal Laminate", 1, "200.00", "0"),
    ]
    open_lrs = client.get("/receivables/lrs", params={"party": "rangoli laminate"}, headers=h).json()
    assert [a["balance"] for a in open_lrs] == ["500.00", "200.00"]

    clerk = add_staff(client, admin, "clerk@shree.example", "clerk")
    assert client.get("/receivables", headers=bearer(clerk)).status_code == 403
    other = register(client, "Other Transport", "o@o.example")
    assert client.get("/receivables", headers=bearer(other)).json()["parties"] == []
    assert client.get(f"/lrs/{half['id']}/account", headers=bearer(other)).status_code == 404


def test_admin_dashboard(client, admin):
    h = bearer(admin)
    home = _truck(client, h, "GJ03AA0001")
    client.patch(f"/trucks/{home}", json={"current_station": "Rajkot"}, headers=h)
    out = _truck(client, h, "GJ03BB0002")
    mid = _lr(client, h, packages=1, to_city="Dhamtari", st_charges="100", freight_by="TBB")
    end = _lr(client, h, packages=1, to_city="Jagdalpur", st_charges="250", freight_by="TBB", value="80000", distance_km=150,
              eway_bill_no="692194190201", consignor_name="Monal Laminate", consignor_gstin=None)
    _lr(client, h, days_ago=40, packages=1, st_charges="1000", freight_by="TBB")
    trip = client.post(
        "/trips",
        json={"truck_id": out, "stops": ["Dhamtari", "Jagdalpur"], "lines": [{"lr_id": mid["id"], "packages": 1}, {"lr_id": end["id"], "packages": 1}]},
        headers=h,
    ).json()
    client.post(f"/trips/{trip['id']}/stops/Dhamtari/deliver", headers=h)

    board = client.get("/dashboard/admin", headers=h).json()
    assert (board["trips_in_transit"], board["trips_partially_delivered"], board["trips_completed_today"]) == (0, 1, 0)
    assert board["trucks"] == [
        {"vehicle_number": "GJ03AA0001", "state": "available", "location": "RAJKOT", "next_stop": None,
         "destination": None, "progress": None, "papers_expired": False},
        {"vehicle_number": "GJ03BB0002", "state": "on_trip", "location": None, "next_stop": "JAGDALPUR",
         "destination": "JAGDALPUR", "progress": "partially_delivered", "papers_expired": False},
    ]
    assert (board["freight_today"], board["freight_this_month"] >= "350.00") == ("350.00", True)
    assert len(board["last_7_days"]) == 7 and board["last_7_days"][-1] == {"date": str(today()), "freight": "350.00"}
    assert (board["receivables_outstanding"], board["receivables_overdue"]) == ("1350.00", "1000.00")
    assert board["top_debtors"][0]["party"] == "Rangoli Laminate"
    # 150 km is one day: the bill on the moving truck lapses at midnight tonight
    assert [(b["lr_number"], b["vehicle_number"]) for b in board["eway_bills_expiring"]] == [(end["lr_number"], "GJ03BB0002")]
    assert {d["name"] for d in board["top_destinations"]} >= {"DHAMTARI", "JAGDALPUR"}

    manager = add_staff(client, admin, "m@shree.example", "manager")
    assert client.get("/dashboard/admin", headers=bearer(manager)).status_code == 403

import datetime as dt

from app.clock import today
from tests.conftest import add_staff, bearer
from tests.test_dispatch import _lr, _truck
from tests.test_lr import NEW_LR
from tests.test_payments import _receipt, _visit
from tests.test_rates import _matrix


def _book(client, h, **changes):
    return client.post("/lrs", json={**NEW_LR, "to_city": "Surat", **changes}, headers=h)


def test_freight_per_kg_or_per_article_is_checked_by_the_server(client, admin):
    h = bearer(admin)
    # Scenario A: 500 kg at Rs 5 per kg
    per_kg = _book(client, h, charge_basis="per_kg", weight="500", rate="5", freight="2500")
    assert per_kg.status_code == 201 and per_kg.json()["charge_basis"] == "per_kg"
    # the chargeable weight is used when given
    assert _book(client, h, charge_basis="per_kg", weight="480", charged_weight="500", rate="5", freight="2500").status_code == 201
    # Scenario B: 100 articles at Rs 20 per article, whatever they weigh
    per_article = _book(client, h, charge_basis="per_article", packages=100, weight="500", rate="20", freight="2000")
    assert per_article.status_code == 201 and per_article.json()["total"] == "2035.00"
    wrong = _book(client, h, charge_basis="per_article", packages=100, weight="500", rate="20", freight="2500")
    assert wrong.status_code == 422 and "Rs 20 per article x 100 = Rs 2000.00" in wrong.text
    assert _book(client, h, charge_basis="per_kg", weight="500", rate="5", freight="2000").status_code == 422
    no_basis = {k: v for k, v in NEW_LR.items() if k != "charge_basis"}
    missing = client.post("/lrs", json={**no_basis, "rate": "5", "freight": "2500", "weight": "500"}, headers=h)
    assert missing.status_code == 422 and "charge_basis" in missing.text
    # the printed rate says what it is per
    page = client.get(f"/lrs/{per_article.json()['id']}/pdf", params={"copy": "white"}, headers=h)
    from tests.test_documents import _pages

    assert "20.00/ART" in _pages(page)[0]


def test_freight_from_the_rate_matrix_is_priced_again(client, admin):
    h = bearer(admin)
    bearings = _matrix(client, h)[0]
    common = {"to_city": "Jagdalpur", "packages": 10, "weight_per_package": "100", "weight": "1000", "rate_rule_id": bearings["id"], "charge_basis": "matrix"}
    assert _book(client, h, **common, rate="5.5", freight="5500").status_code == 201
    typed_over = _book(client, h, **common, rate="5.5", freight="5000")
    assert typed_over.status_code == 422 and "gives Rs 5,500.00" in typed_over.text
    assert _book(client, h, **{**common, "rate_rule_id": None}, freight="5500").status_code == 422


def test_due_dates_follow_each_customers_terms(client, admin):
    h = bearer(admin)
    account = lambda lr: client.get(f"/lrs/{lr['id']}/account", headers=h).json()
    terms = lambda name, **t: client.put("/credit-terms", json={"payer_name": name, **t}, headers=h)
    assert terms("A", payment_terms="credit").status_code == 422  # credit needs a limit and days
    assert terms("A", payment_terms="advance", credit_days=7, credit_limit="100").status_code == 422
    terms("Advance Co", payment_terms="advance")
    terms("Credit Co", payment_terms="credit", credit_limit="50000", credit_days=15)

    advance = _lr(client, h, days_ago=3, st_charges="100", consignee_name="Advance Co")
    on_credit = _lr(client, h, days_ago=3, st_charges="100", consignee_name="Credit Co", packages=1)
    default = _lr(client, h, days_ago=3, st_charges="100", consignee_name="Walk In", packages=1)
    assert account(advance)["due_on"] == str(today() - dt.timedelta(days=3))
    # on credit, nothing is due until delivery; then 15 days later
    assert account(on_credit)["due_on"] is None and account(default)["due_on"] is None
    trip = client.post(
        "/trips",
        json={"truck_id": _truck(client, h), "stops": ["Surat"], "lines": [{"lr_id": on_credit["id"], "packages": 1}, {"lr_id": default["id"], "packages": 1}]},
        headers=h,
    ).json()
    client.post(f"/trips/{trip['id']}/stops/SURAT/deliver", headers=h)
    assert account(on_credit)["due_on"] == str(today() + dt.timedelta(days=15))
    assert account(default)["due_on"] == str(today())  # no terms: pays at delivery
    # counted from booking instead, if the company prefers
    client.patch("/lrs/settings", json={"credit_from": "booking"}, headers=h)
    assert account(on_credit)["due_on"] == str(today() + dt.timedelta(days=12))
    listed = {p["party"]: p for p in client.get("/receivables", headers=h).json()["parties"]}
    assert (listed["Credit Co"]["payment_terms"], listed["Credit Co"]["credit_limit"]) == ("credit", "50000.00")
    assert (listed["Walk In"]["payment_terms"], listed["Walk In"]["credit_limit"]) == ("at_delivery", None)
    credit_row = next(t for t in client.get("/credit-terms", headers=h).json() if t["payer_name"] == "Credit Co")
    assert (credit_row["outstanding"], credit_row["available"]) == ("100.00", "49900.00")


def test_bookings_are_held_for_customers_who_have_not_paid(client, admin):
    h = bearer(admin)
    clerk = bearer(add_staff(client, admin, "c@shree.example", "clerk"))
    _lr(client, h, days_ago=40, st_charges="500", freight_by="Paid")  # unpaid since booking
    # holds are off until the owner sets the date controls start, so old LRs cannot block everyone
    assert _book(client, clerk, charge_basis="per_kg").status_code == 201
    client.patch("/lrs/settings", json={"credit_controls_from": str(today() - dt.timedelta(days=60)), "overdue_hold_days": 15}, headers=h)
    held = _book(client, clerk, charge_basis="per_kg", freight_by="Paid")
    assert held.status_code == 409 and "Rangoli Laminate has Rs 500.00 overdue since" in held.json()["error"]["message"]
    # a clerk cannot override; the owner can, with a reason that is kept on the LR
    assert _book(client, clerk, charge_basis="per_kg", freight_by="Paid", credit_override_reason="please").status_code == 409
    allowed = _book(client, h, charge_basis="per_kg", freight_by="Paid", credit_override_reason="Promised to clear on Friday")
    assert allowed.status_code == 201 and allowed.json()["credit_override_reason"] == "Promised to clear on Friday"
    # an advance customer must be booked as Paid
    client.put("/credit-terms", json={"payer_name": "Jalaram Enterprise", "payment_terms": "advance"}, headers=h)
    advance = _book(client, clerk, charge_basis="per_kg")
    assert advance.status_code == 409 and "pays in advance" in advance.json()["error"]["message"]


def test_release_rules_follow_payment_terms(client, admin):
    h = bearer(admin)
    clerk = add_staff(client, admin, "s@shree.example", "register_clerk")
    client.put("/credit-terms", json={"payer_name": "Jalaram Enterprise", "payment_terms": "before_delivery"}, headers=h)
    lr = _lr(client, h, st_charges="700")
    refused = client.post("/gate-passes", json={"lr_ids": [lr["id"]]}, headers=bearer(clerk))
    assert refused.status_code == 409 and "pays before delivery" in refused.json()["error"]["message"]
    _visit(client, add_staff(client, admin, "r@shree.example", "collector"), _receipt(client, clerk, lr), "paid", method="cash", amount="700")
    assert client.post("/gate-passes", json={"lr_ids": [lr["id"]]}, headers=bearer(clerk)).json()["lines"][0]["basis"] == "paid"


def test_ageing_and_where_the_money_is_stuck(client, admin):
    h = bearer(admin)
    collector = add_staff(client, admin, "r@shree.example", "collector")
    for days, amount, name in ((3, "100", "Alpha Co"), (10, "200", "Alpha Co"), (20, "300", "Beta Co"), (45, "400", "Beta Co"), (90, "500", "Chetan Co")):
        _lr(client, h, days_ago=days, st_charges=amount, freight_by="Paid", consignor_name=name, consignor_gstin=None, consignor_pan="AABCR4141H", consignee_pan="AWCPP8803A", consignee_gstin=None)
    _lr(client, h, st_charges="50", freight_by="Paid", consignor_name="Alpha Co", consignor_gstin=None, consignor_pan="AABCR4141H", consignee_pan="AWCPP8803A", consignee_gstin=None)
    ageing = client.get("/receivables/ageing", headers=h).json()
    rows = {r["party"]: r for r in ageing["rows"]}
    # due today is not yet late
    assert (rows["Alpha Co"]["not_due"], rows["Alpha Co"]["days_0_7"], rows["Alpha Co"]["days_8_15"]) == ("50.00", "100.00", "200.00")
    assert (rows["Beta Co"]["days_16_30"], rows["Beta Co"]["days_31_60"], rows["Chetan Co"]["days_60_plus"]) == ("300.00", "400.00", "500.00")
    assert ageing["totals"]["total"] == "1550.00"
    assert [r["party"] for r in ageing["rows"]] == ["Beta Co", "Chetan Co", "Alpha Co"]

    # a customer pays two old LRs late: a repeat late payer
    for days in (60, 50):
        lr = _lr(client, h, days_ago=days, st_charges="10", freight_by="Paid", consignor_name="Slow Payer", consignor_gstin=None, consignor_pan="AABCR4141H", consignee_pan="AWCPP8803A", consignee_gstin=None)
        _visit(client, collector, _receipt(client, admin, lr), "paid", method="cash", amount="10")
    client.put("/credit-terms", json={"payer_name": "Beta Co", "payment_terms": "credit", "credit_limit": "800", "credit_days": 30}, headers=h)
    stuck = client.get("/receivables/priorities", headers=h).json()
    assert stuck["largest"][0]["party"] == "Beta Co"
    assert stuck["oldest_overdue"][0] == {"party": "Chetan Co", "lr_number": stuck["oldest_overdue"][0]["lr_number"], "balance": "500.00", "days_overdue": 90}
    assert stuck["near_limit"] == [{"party": "Beta Co", "outstanding": "700.00", "credit_limit": "800.00", "used_pct": 88}]
    assert stuck["late_payers"] == [{"party": "Slow Payer", "lrs_paid": 2, "lrs_paid_late": 2, "average_days_late": 55}]


def test_a_retried_request_does_not_book_or_collect_twice(client, admin):
    h = bearer(admin)
    key = {"Idempotency-Key": "lr-retry-0001"}
    first = client.post("/lrs", json={**NEW_LR, "charge_basis": "per_kg"}, headers={**h, **key})
    again = client.post("/lrs", json={**NEW_LR, "charge_basis": "per_kg"}, headers={**h, **key})
    assert first.status_code == again.status_code == 201 and first.json()["lr_number"] == again.json()["lr_number"] == "LR-1"
    assert len(client.get("/lrs", headers=h).json()) == 1
    # a failed request leaves no key behind, so it can be retried for real
    bad = client.post("/lrs", json={**NEW_LR, "charge_basis": "per_kg", "freight": "5"}, headers={**h, "Idempotency-Key": "lr-retry-0002"})
    assert bad.status_code == 422
    # a key cannot be reused for something else
    receipt = client.post("/receipts", json={"lr_ids": [first.json()["id"]]}, headers={**h, **key})
    assert receipt.status_code == 422 and receipt.json()["error"]["code"] == "key_reused"
    receipt = _receipt(client, admin, first.json())
    visit_key = {"Idempotency-Key": "visit-0001-abc"}
    body = {"outcome": "part_paid", "payment": {"method": "cash", "amount": "10"}}
    one = client.post(f"/receipts/{receipt['id']}/visits", json=body, headers={**h, **visit_key})
    two = client.post(f"/receipts/{receipt['id']}/visits", json=body, headers={**h, **visit_key})
    assert one.json() == two.json() and len(two.json()["collections"]) == 1
    other = bearer(add_staff(client, admin, "x@shree.example", "manager"))
    assert client.post(f"/receipts/{receipt['id']}/visits", json=body, headers={**other, **visit_key}).status_code == 422

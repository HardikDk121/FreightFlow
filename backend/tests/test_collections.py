import datetime as dt

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.clock import today
from app.notify import get_outbox
from app.main import app
from tests.conftest import add_staff, bearer, register
from tests.test_dispatch import _lr
from tests.test_lr import NEW_LR
from tests.test_payments import _receipt, _visit
from tests.test_tenancy import SCOPE, app_engine


@pytest.fixture
def team(client, admin):
    """The Raipur set-up: one collector, one register clerk, and the owner (admin)."""
    return {
        "owner": admin,
        "collector": add_staff(client, admin, "ramesh@shree.example", "collector"),
        "clerk": add_staff(client, admin, "suresh@shree.example", "register_clerk"),
    }


def _user_id(client, tokens):
    return client.get("/me", headers=bearer(tokens)).json()["id"]


def _ten_customers(client, h):
    """Ten to-pay LRs of Rs 1,000 each, for ten different consignees."""
    return [_lr(client, h, st_charges="1000", consignee_name=f"Customer {n}") for n in range(10)]


def test_receipts_are_numbered_by_the_app_and_take_the_amount_from_the_lrs(client, team):
    h = bearer(team["owner"])
    first, second = _lr(client, h, st_charges="600"), _lr(client, h, st_charges="400", days_ago=2)
    other_payer = _lr(client, h, st_charges="100", consignee_name="Someone Else")
    assert client.post("/receipts", json={"lr_ids": [first["id"], other_payer["id"]]}, headers=h).status_code == 409
    assert client.post("/receipts", json={"lr_ids": [first["id"]]}, headers=bearer(team["collector"])).status_code == 403

    receipt = _receipt(client, team["clerk"], first, second)
    assert (receipt["receipt_number"], receipt["amount"], receipt["balance"], receipt["payer_name"]) == ("MR-1", "1000.00", "1000.00", "Jalaram Enterprise")
    assert [line["lr_number"] for line in receipt["lines"]] == [second["lr_number"], first["lr_number"]]  # oldest first
    assert len(receipt["verify_token"]) > 16
    # one open receipt per LR, so the same money cannot be demanded twice
    assert client.post("/receipts", json={"lr_ids": [first["id"]]}, headers=h).status_code == 409
    assert client.get(f"/receipts/{receipt['id']}", headers=h).json()["verify_token"] is None

    # anyone holding the paper can check it against the company's record, without signing in
    checked = client.get(f"/receipts/verify/{receipt['verify_token']}").json()
    assert (checked["receipt_number"], checked["amount"], checked["status"], checked["company_name"]) == ("MR-1", "1000.00", "open", "Shree Transport")
    assert client.get("/receipts/verify/forged-token-forged-token").status_code == 404
    page = client.get(f"/r/{receipt['verify_token']}")
    assert page.status_code == 200 and "MR-1" in page.text and "Not yet fully paid" in page.text
    assert client.get("/r/forged-token-forged-token").status_code == 404
    # printed any time with the same QR, because the token is derived, not stored
    client.patch("/company", json={"bank_details": "Shree Transport\nICICI Bank A/c 123456789012\nIFSC ICIC0001234"}, headers=h)
    pdf = client.get(f"/receipts/{receipt['id']}/pdf", headers=bearer(team["collector"]))
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    # a receipt with nothing collected can be cancelled; its number is not reused
    assert client.post(f"/receipts/{receipt['id']}/cancel", json={"reason": "no"}, headers=h).status_code == 422
    cancelled = client.post(f"/receipts/{receipt['id']}/cancel", json={"reason": "Wrong LRs"}, headers=h).json()
    assert cancelled["status"] == "cancelled"
    assert _receipt(client, team["clerk"], first)["receipt_number"] == "MR-2"


def test_visits_record_what_happened_and_tell_the_customer(client, team):
    h = bearer(team["owner"])
    outbox = app.dependency_overrides[get_outbox]()
    lr = _lr(client, h, st_charges="1000")
    receipt = _receipt(client, team["clerk"], lr)
    collector = team["collector"]

    later = _visit(client, collector, receipt, "come_later")
    assert later.status_code == 422  # needs the promised date
    tomorrow = str(today() + dt.timedelta(days=1))
    later = client.post(f"/receipts/{receipt['id']}/visits", json={"outcome": "come_later", "promised_on": tomorrow}, headers=bearer(collector)).json()
    assert (later["status"], later["promised_on"], later["visits"][0]["collector"]) == ("open", tomorrow, "Ravi")
    assert outbox.texts == []  # nothing collected, nothing to tell

    assert _visit(client, collector, receipt, "paid", method="cash", amount="900").status_code == 422  # not the full amount
    assert _visit(client, collector, receipt, "part_paid", method="upi", amount="400").status_code == 422  # UPI needs its UTR
    part = _visit(client, collector, receipt, "part_paid", method="cash", amount="400").json()
    assert (part["collected"], part["balance"], part["status"]) == ("400.00", "600.00", "open")
    phone, message = outbox.texts[-1]
    assert phone == "9327410932" and "Rs 400.00 received in cash" in message and "You now owe Rs 600.00" in message
    assert outbox.whatsapps[-1] == outbox.texts[-1]

    assert _visit(client, collector, receipt, "paid", method="cash", amount="700").status_code == 409  # more than is left
    paid = _visit(client, collector, receipt, "paid", method="upi", amount="600", utr="432112345678").json()
    assert (paid["status"], paid["balance"]) == ("settled", "0")
    assert [(c["method"], c["custody"]) for c in paid["collections"]] == [("cash", "with_collector"), ("upi", "awaiting_bank")]
    # the same UPI reference cannot settle a second debt
    other = _receipt(client, team["clerk"], _lr(client, h, st_charges="600"))
    assert _visit(client, collector, other, "paid", method="upi", amount="600", utr="432112345678").status_code == 409


def test_cash_limits_for_collectors_and_by_law(client, team):
    h = bearer(team["owner"])
    big = _receipt(client, team["clerk"], _lr(client, h, st_charges="30000"))
    refused = _visit(client, team["collector"], big, "part_paid", method="cash", amount="25000.01")
    assert refused.status_code == 409 and "goes to the owner or the bank" in refused.json()["error"]["message"]
    assert _visit(client, team["collector"], big, "part_paid", method="cash", amount="25000").status_code == 201
    assert _visit(client, team["collector"], big, "paid", method="cash", amount="5000").status_code == 409
    # the owner may take more, but nobody may take Rs 2 lakh or more in cash from one customer in a day
    huge = _receipt(client, team["clerk"], _lr(client, h, st_charges="250000", consignee_name="Big Buyer"))
    assert _visit(client, team["owner"], huge, "part_paid", method="cash", amount="150000").status_code == 201
    illegal = _visit(client, team["owner"], huge, "part_paid", method="cash", amount="50000")
    assert illegal.status_code == 409 and "not allowed by law" in illegal.json()["error"]["message"]
    assert _visit(client, team["owner"], huge, "part_paid", method="cash", amount="49999.99").status_code == 201


def test_worked_example_ten_customers_and_a_missing_thousand(client, team):
    """The design's example: Rs 10,000 due, six pay by UPI and four in cash, and Rs 1,000 goes missing
    between the collector and the register. The app shows exactly where."""
    h = bearer(team["owner"])
    lrs = _ten_customers(client, h)
    collector, clerk = team["collector"], team["clerk"]
    for n, lr in enumerate(lrs):
        receipt = _receipt(client, clerk, lr)
        if n < 6:
            _visit(client, collector, receipt, "paid", method="upi", amount="1000", utr=f"43211234567{n}")
        else:
            _visit(client, collector, receipt, "paid", method="cash", amount="1000")

    held = client.get("/custody/me", headers=bearer(collector)).json()
    assert (held["cash"], held["cheque_count"]) == ("4000.00", 0)
    assert [c["cash"] for c in client.get("/custody", headers=bearer(clerk)).json()] == ["4000.00"]
    assert client.get("/custody", headers=bearer(collector)).status_code == 403
    collector_id = _user_id(client, collector)
    assert client.get(f"/custody/{collector_id}", headers=bearer(clerk)).json()["cash"] == "4000.00"

    # the collector hands in Rs 3,000; the clerk counts it and the shortage is recorded on the spot
    assert client.post("/handovers", json={"from_user_id": collector_id, "counted_cash": "4000.01"}, headers=bearer(clerk)).status_code == 409
    handover = client.post("/handovers", json={"from_user_id": collector_id, "counted_cash": "3000"}, headers=bearer(clerk)).json()
    assert (handover["expected_cash"], handover["counted_cash"], handover["shortage"]) == ("4000.00", "3000.00", "1000.00")
    assert client.get("/custody/me", headers=bearer(collector)).json()["cash"] == "0"
    assert client.post(f"/handovers/{handover['id']}/confirm", headers=bearer(clerk)).status_code == 403
    assert client.post(f"/handovers/{handover['id']}/confirm", headers=bearer(collector)).json()["from_confirmed_at"] is not None

    deposit = client.post("/deposits", json={"cash_amount": "3000", "slip_reference": "slip 1"}, headers=bearer(clerk)).json()
    assert (deposit["deposit_number"], deposit["cash_amount"], deposit["shortage"], deposit["status"]) == ("DEP-1", "3000.00", "0.00", "in_transit")

    trail = client.get("/collections/overview", headers=h).json()
    assert (trail["collected_upi"], trail["collected_cash"]) == ("6000.00", "4000.00")
    assert (trail["handed_over_expected"], trail["handed_over_counted"], trail["shortages"]) == ("4000.00", "3000.00", "1000.00")
    assert (trail["upi_unconfirmed"], trail["deposits_in_transit"], trail["receivable"]) == ("6000.00", "3000.00", "0")
    shortage = next(e for e in trail["exceptions"] if e["kind"] == "shortage")
    assert shortage["message"] == "Shortage of Rs 1,000.00 by Ravi at handover, awaiting your decision."

    # the owner decides: recovered from salary, with a reason, once
    shortage_id = client.get("/shortages", params={"status": "open"}, headers=h).json()[0]["id"]
    bad = client.post(f"/shortages/{shortage_id}/decide", json={"decision": "recover_from_salary", "note": "x"}, headers=h)
    assert bad.status_code == 422
    decided = client.post(
        f"/shortages/{shortage_id}/decide",
        json={"decision": "recover_from_salary", "salary_month": "2026-12-15", "note": "Agreed with Ramesh"},
        headers=h,
    ).json()
    assert (decided["status"], decided["salary_month"]) == ("recover_from_salary", "2026-12-01")
    assert client.post(f"/shortages/{shortage_id}/decide", json={"decision": "found", "note": "x"}, headers=h).status_code == 409
    assert client.post(f"/shortages/{shortage_id}/decide", json={"decision": "found", "note": "x"}, headers=bearer(clerk)).status_code == 403
    assert "Handed over Rs 3,000 of Rs 4,000 expected" in client.get("/collections/daily-summary", headers=h).json()["text"]


def test_nobody_receives_their_own_cash_and_cheques_travel_with_the_handover(client, team):
    h = bearer(team["owner"])
    clerk, collector = team["clerk"], team["collector"]
    clerk_id, collector_id = _user_id(client, clerk), _user_id(client, collector)
    assert client.post("/handovers", json={"from_user_id": collector_id, "counted_cash": "0"}, headers=bearer(clerk)).status_code == 409
    receipt = _receipt(client, clerk, _lr(client, h, st_charges="5000"))
    _visit(client, collector, receipt, "part_paid", method="cheque", amount="3000", cheque_number="004512", cheque_bank="SBI")
    _visit(client, collector, receipt, "paid", method="cash", amount="2000")
    assert client.post("/handovers", json={"from_user_id": clerk_id, "counted_cash": "0"}, headers=bearer(clerk)).status_code == 409
    assert client.post("/handovers", json={"from_user_id": collector_id, "counted_cash": "2000"}, headers=bearer(collector)).status_code == 403

    cheque_id = client.get("/custody/me", headers=bearer(collector)).json()["items"][0]["collection_id"]
    handover = client.post(
        "/handovers", json={"from_user_id": collector_id, "counted_cash": "2000", "cheque_ids": [cheque_id]}, headers=bearer(clerk)
    ).json()
    assert (handover["shortage"], handover["cheque_count"]) == ("0.00", 1)
    with_clerk = client.get("/custody/me", headers=bearer(clerk)).json()
    assert (with_clerk["cash"], with_clerk["cheques"], with_clerk["cheque_count"]) == ("2000.00", "3000.00", 1)
    assert client.post("/deposits", json={"cash_amount": "2000.01"}, headers=bearer(clerk)).status_code == 409
    deposit = client.post("/deposits", json={"cash_amount": "1900", "cheque_ids": [cheque_id]}, headers=bearer(clerk)).json()
    # Rs 100 less banked than held is a shortage against the person who banked it
    assert (deposit["shortage"], deposit["cheque_count"], deposit["cheque_total"]) == ("100.00", 1, "3000.00")
    assert client.get("/custody/me", headers=bearer(clerk)).json()["items"] == []
    assert [(s["name"], s["amount"], s["source"]) for s in client.get("/shortages", headers=h).json()] == [("Ravi", "100.00", "deposit")]


def test_release_needs_payment_standing_credit_or_the_owners_approval(client, team):
    h = bearer(team["owner"])
    clerk = team["clerk"]
    gate = lambda lr: client.post("/gate-passes", json={"lr_ids": [lr["id"]]}, headers=bearer(clerk))

    unpaid = _lr(client, h, st_charges="5000")
    refused = gate(unpaid)
    assert refused.status_code == 409 and "ask the owner to approve the release" in refused.json()["error"]["message"]
    assert gate(_lr(client, h, st_charges="100", freight_by="TBB")).json()["lines"][0]["basis"] == "not_to_pay"

    # standing credit for a regular customer: up to Rs 8,000 and 30 days
    assert client.put("/credit-terms", json={"payer_name": "jalaram enterprise", "credit_limit": "8000", "credit_days": 30}, headers=bearer(clerk)).status_code == 403
    terms = client.put("/credit-terms", json={"payer_name": "Jalaram Enterprise", "credit_limit": "8000", "credit_days": 30}, headers=h).json()
    assert (terms["outstanding"], terms["approved_by"]) == ("5000.00", "Asha")
    first = gate(unpaid).json()
    assert (first["gate_pass_number"], first["lines"][0]["basis"]) == ("GP-2", "credit")  # GP-1 went to the TBB LR
    assert gate(unpaid).status_code == 409  # one open gate pass per LR
    # the customer would now owe more than the limit: only the owner can book it, saying why
    client.patch("/lrs/settings", json={"credit_controls_from": str(today() - dt.timedelta(days=365))}, headers=h)
    held = client.post("/lrs", json={**NEW_LR, "to_city": "Surat", "st_charges": "4000"}, headers=bearer(add_staff(client, team["owner"], "b@shree.example", "clerk")))
    assert held.status_code == 409 and held.json()["error"]["code"] == "credit_hold"
    over_lr = _lr(client, h, st_charges="4000", credit_override_reason="Big order, agreed by phone")
    assert over_lr["credit_override_reason"] == "Big order, agreed by phone"
    over = gate(over_lr)
    assert over.status_code == 409 and "over their credit" in over.json()["error"]["message"]
    # an old unpaid LR also stops credit, however small the total
    client.put("/credit-terms", json={"payer_name": "Jalaram Enterprise", "credit_limit": "100000", "credit_days": 30}, headers=h)
    _lr(client, h, st_charges="10", days_ago=40, credit_override_reason="Old booking entered late")
    assert gate(_lr(client, h, st_charges="10")).status_code == 409

    # a one-off approval from the owner releases it anyway
    stuck = _lr(client, h, st_charges="20")
    assert client.post(f"/lrs/{stuck['id']}/release-approval", json={"reason": "Known customer"}, headers=bearer(clerk)).status_code == 403
    assert client.post(f"/lrs/{stuck['id']}/release-approval", json={"reason": "Known customer"}, headers=h).status_code == 204
    assert gate(stuck).json()["lines"][0]["basis"] == "approved"
    # paid in full releases without anyone's approval
    paid = _lr(client, h, st_charges="300", consignee_name="Walk In")
    _visit(client, team["collector"], _receipt(client, clerk, paid), "paid", method="cash", amount="300")
    assert gate(paid).json()["lines"][0]["basis"] == "paid"


def test_a_bounced_cheque_is_owed_again(client, team):
    h = bearer(team["owner"])
    lr = _lr(client, h, st_charges="3000")
    receipt = _receipt(client, team["clerk"], lr)
    settled = _visit(client, team["collector"], receipt, "paid", method="cheque", amount="3000", cheque_number="123456", cheque_bank="HDFC").json()
    assert settled["status"] == "settled"
    cheque = settled["collections"][0]
    assert client.post(f"/collections/{cheque['id']}/fail", json={"reason": "Bounced"}, headers=bearer(team["clerk"])).status_code == 403
    failed = client.post(f"/collections/{cheque['id']}/fail", json={"reason": "Bounced: funds insufficient"}, headers=h).json()
    assert (failed["status"], failed["custody"]) == ("failed", "failed")
    reopened = client.get(f"/receipts/{receipt['id']}", headers=h).json()
    assert (reopened["status"], reopened["balance"]) == ("open", "3000.00")
    assert any(e["kind"] == "payment_failed" for e in client.get("/collections/overview", headers=h).json()["exceptions"])
    # the same cheque number can be recorded again once the first was marked failed (a re-presented cheque)
    assert _visit(client, team["collector"], reopened, "paid", method="cheque", amount="3000", cheque_number="123456", cheque_bank="HDFC").status_code == 201


def test_collections_cannot_be_rewritten_and_stay_private(client, team):
    h = bearer(team["owner"])
    receipt = _receipt(client, team["clerk"], _lr(client, h, st_charges="1000"))
    _visit(client, team["collector"], receipt, "paid", method="cash", amount="1000")
    company_id = client.get("/company", headers=h).json()["id"]
    for statement in (
        "UPDATE collection SET amount = 1",
        "UPDATE collection SET collected_by = collected_by",
        "UPDATE money_receipt SET amount = 1",
        "UPDATE collection_allocation SET amount = 1",
        "DELETE FROM collection",
        "UPDATE cash_handover SET counted_cash = 1",
    ):
        with app_engine.connect() as conn:
            conn.execute(text(SCOPE), {"c": company_id})
            with pytest.raises(DBAPIError, match="permission denied"):
                conn.execute(text(statement))
            conn.rollback()
    other = register(client, "Other Transport", "o@o.example")
    assert client.get(f"/receipts/{receipt['id']}", headers=bearer(other)).status_code == 404
    assert client.get("/receipts", headers=bearer(other)).json() == []
    assert client.get("/custody/me", headers=bearer(other)).json()["items"] == []

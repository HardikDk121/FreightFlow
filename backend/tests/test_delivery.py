"""Gate passes as on the paper pad, and proof of delivery that does not depend on someone's word."""

import datetime as dt
import json

from app.clock import today
from tests.conftest import add_staff, bearer
from tests.test_dispatch import _lr
from tests.test_payments import _receipt, _visit

SIGNATURE = [[[1, 1], [5, 9], [12, 4], [20, 15], [26, 6]], [[30, 2], [34, 12], [40, 5], [46, 14]]]
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 2000


def _proof(**changes):
    body = {"delivered_at": dt.datetime.now(dt.UTC).isoformat(), "receiver_name": "Mahesh (Noble Marketing)", "signature": SIGNATURE,
            "latitude": 21.2514, "longitude": 81.6296, "accuracy_m": 12}
    return {"proof": json.dumps({**body, **changes})}


def test_a_gate_pass_releases_one_consignees_lrs_and_prints_like_the_pad(client, admin):
    h = bearer(admin)
    clerk = add_staff(client, admin, "s@shree.example", "register_clerk")
    paid = _lr(client, h, st_charges="35", consignee_name="Noble Marketing RPR")
    billed = _lr(client, h, st_charges="35", consignee_name="noble marketing rpr", freight_by="TBB", packages=3)
    other = _lr(client, h, st_charges="35", consignee_name="Someone Else", freight_by="TBB")
    _visit(client, add_staff(client, admin, "r@shree.example", "collector"), _receipt(client, clerk, paid), "paid", method="cash", amount="35")

    assert client.post("/gate-passes", json={"lr_ids": [paid["id"], other["id"]]}, headers=bearer(clerk)).status_code == 409
    gp = client.post("/gate-passes", json={"lr_ids": [paid["id"], billed["id"]], "auto_no": "cg04ab1234", "driver_name": "Sunil"}, headers=bearer(clerk))
    assert gp.status_code == 201, gp.text
    body = gp.json()
    assert (body["gate_pass_number"], body["auto_no"], body["status"]) == ("GP-1", "CG04AB1234", "issued")
    assert [(l["packages"], l["payment"]) for l in body["lines"]] == [(paid["packages"], "Paid"), (3, "TBB")]
    # an LR on an open gate pass cannot go on a second one
    assert client.post("/gate-passes", json={"lr_ids": [paid["id"]]}, headers=bearer(clerk)).status_code == 409
    pdf = client.get(f"/gate-passes/{body['id']}/pdf", headers=bearer(clerk))
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_proof_of_delivery_starts_the_credit_clock_and_cannot_be_undone_by_staff(client, admin):
    h = bearer(admin)
    clerk = bearer(add_staff(client, admin, "s@shree.example", "register_clerk"))
    collector = bearer(add_staff(client, admin, "r@shree.example", "collector"))
    client.put("/credit-terms", json={"payer_name": "Jalaram Enterprise", "payment_terms": "credit", "credit_limit": "50000", "credit_days": 15}, headers=h)
    lr = _lr(client, h, st_charges="500", days_ago=5)
    gp = client.post("/gate-passes", json={"lr_ids": [lr["id"]]}, headers=clerk).json()
    assert client.get(f"/lrs/{lr['id']}/account", headers=h).json()["due_on"] is None  # on credit, not delivered yet

    url = f"/gate-passes/{gp['id']}/delivery"
    future = (dt.datetime.now(dt.UTC) + dt.timedelta(hours=2)).isoformat()
    assert client.post(url, data=_proof(delivered_at=future), headers=collector).json()["error"]["code"] == "future_time"
    assert client.post(url, data=_proof(signature=[[[1, 1], [2, 2]]]), headers=collector).status_code == 422
    assert client.post(url, data=_proof(), files={"photo": ("p.txt", b"not a photo", "text/plain")}, headers=collector).json()["error"]["code"] == "not_a_photo"
    done = client.post(url, data=_proof(), files={"photo": ("gp.jpg", JPEG, "image/jpeg")}, headers=collector)
    assert done.status_code == 200, done.text
    body = done.json()
    assert (body["status"], body["receiver_name"], body["has_photo"], body["latitude"]) == ("delivered", "Mahesh (Noble Marketing)", True, 21.2514)
    assert client.get(f"/gate-passes/{gp['id']}/photo", headers=h).content == JPEG
    # due 15 days after the consignee signed
    assert client.get(f"/lrs/{lr['id']}/account", headers=h).json()["due_on"] == str(today() + dt.timedelta(days=15))
    assert client.post(url, data=_proof(), headers=collector).status_code == 409

    # staff cannot undo a delivery; the owner can, with a reason, and it stays on record
    assert client.post(f"/gate-passes/{gp['id']}/void", json={"reason": "Marked by mistake"}, headers=clerk).status_code == 403
    voided = client.post(f"/gate-passes/{gp['id']}/void", json={"reason": "Wrong consignee signed"}, headers=h).json()
    assert (voided["status"], voided["void_reason"], voided["receiver_name"]) == ("void", "Wrong consignee signed", "Mahesh (Noble Marketing)")
    assert client.get(f"/lrs/{lr['id']}/account", headers=h).json()["due_on"] is None
    # the LR can go on a new gate pass
    assert client.post("/gate-passes", json={"lr_ids": [lr["id"]]}, headers=clerk).status_code == 201


def test_a_proof_sent_twice_from_a_phone_that_was_offline_is_recorded_once(client, admin):
    h = bearer(admin)
    collector = bearer(add_staff(client, admin, "r@shree.example", "collector"))
    lr = _lr(client, h, st_charges="0", freight_by="TBB")
    gp = client.post("/gate-passes", json={"lr_ids": [lr["id"]]}, headers=h).json()
    from sqlalchemy import text

    from tests.conftest import owner_engine

    with owner_engine.begin() as conn:  # issued this morning; signed for at noon; the phone was offline until now
        conn.execute(text("UPDATE gate_pass SET issued_at = now() - interval '3 hours'"))
    signed_earlier = (dt.datetime.now(dt.UTC) - dt.timedelta(minutes=40)).isoformat()
    key = {"Idempotency-Key": "pod-offline-0001"}
    first = client.post(f"/gate-passes/{gp['id']}/delivery", data=_proof(delivered_at=signed_earlier), headers={**collector, **key})
    again = client.post(f"/gate-passes/{gp['id']}/delivery", data=_proof(delivered_at=signed_earlier), headers={**collector, **key})
    assert first.status_code == again.status_code == 200 and first.json() == again.json()
    assert first.json()["delivered_at"].startswith(signed_earlier[:16])


def test_release_requests_go_to_the_owner(client, admin):
    h = bearer(admin)
    clerk = bearer(add_staff(client, admin, "s@shree.example", "register_clerk"))
    lr = _lr(client, h, st_charges="900")
    assert client.post("/gate-passes", json={"lr_ids": [lr["id"]]}, headers=clerk).status_code == 409
    request = client.post(f"/lrs/{lr['id']}/release-request", json={"reason": "Regular party, pays Friday"}, headers=clerk)
    assert request.status_code == 201
    assert client.post(f"/lrs/{lr['id']}/release-request", json={"reason": "again"}, headers=clerk).status_code == 409
    pending = client.get("/approvals", headers=h).json()
    assert [(p["lr_number"], p["amount_owed"], p["requested_by"]) for p in pending] == [(lr["lr_number"], "900.00", "Ravi")]
    assert client.post(f"/approvals/{pending[0]['id']}/decide", json={"approve": True}, headers=clerk).status_code == 403
    decided = client.post(f"/approvals/{pending[0]['id']}/decide", json={"approve": True, "note": "OK this once"}, headers=h).json()
    assert (decided["status"], decided["decided_by"]) == ("approved", "Asha")
    assert client.post("/gate-passes", json={"lr_ids": [lr["id"]]}, headers=clerk).json()["lines"][0]["basis"] == "approved"


def test_money_receipt_carries_destination_charges_and_continues_the_paper_series(client, admin):
    h = bearer(admin)
    lr = _lr(client, h, rate="0", freight="0", st_charges="35", weight="100")
    client.patch("/lrs/settings", json={"receipt_prefix": "", "next_receipt_number": 90013}, headers=h)
    receipt = client.post(
        "/receipts",
        json={"lr_ids": [lr["id"]], "charges": [{"lr_id": lr["id"], "kind": "labour", "amount": "40"}, {"lr_id": lr["id"], "kind": "demurrage", "amount": "60"}]},
        headers=h,
    ).json()
    assert (receipt["receipt_number"], receipt["amount"]) == ("90013", "135.00")
    line = receipt["lines"][0]
    assert (line["st_charge"], line["labour"], line["demurrage"], line["dc_charge"]) == ("35.00", "40.00", "60.00", "0")
    assert client.get(f"/lrs/{lr['id']}/account", headers=h).json()["balance"] == "135.00"
    # cancelling the receipt removes its charges from what is owed
    client.post(f"/receipts/{receipt['id']}/cancel", json={"reason": "Charges wrong"}, headers=h)
    assert client.get(f"/lrs/{lr['id']}/account", headers=h).json()["balance"] == "35.00"
    # the series cannot be moved back onto a used number
    assert client.patch("/lrs/settings", json={"next_receipt_number": 90013}, headers=h).status_code == 409
    pdf = client.get(f"/receipts/{receipt['id']}/pdf", headers=h)
    assert pdf.status_code == 200
    assert client.post("/receipts", json={"lr_ids": [lr["id"]], "charges": [{"lr_id": lr["id"], "kind": "labour", "amount": "1"}, {"lr_id": lr["id"], "kind": "labour", "amount": "2"}]}, headers=h).status_code == 409

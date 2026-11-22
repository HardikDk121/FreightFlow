"""Hired trucks, truck owner payments, trip profit, quotes, contracts and usual transit times."""

import datetime as dt

from sqlalchemy import text

from app.clock import today
from app.main import app
from app.notify import get_outbox
from tests.conftest import add_staff, bearer, owner_engine
from tests.test_analytics import _book, _period
from tests.test_dispatch import _truck


def _owner(client, h, name="Ramesh Roadlines", phone="9825011111"):
    r = client.post("/vendors", json={"name": name, "phone": phone, "pan": "ABCPR1234K"}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


_TRUCKS = iter(f"GJ03AB{n:04d}" for n in range(1, 10000))


def _trip(client, h, lrs, stops=("Raipur",)):
    """A trip on a fresh hired truck (one open trip per truck)."""
    r = client.post("/trips", json={"truck_id": _truck(client, h, next(_TRUCKS)), "stops": list(stops), "lines": [{"lr_id": lr["id"], "packages": lr["packages"]} for lr in lrs]}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def test_trip_profit_after_paying_the_truck_owner(client, admin):
    h = bearer(admin)
    accountant = bearer(add_staff(client, admin, "a@shree.example", "accountant"))
    lr1 = _book(client, h, "Alpha", "Raipur", 1, "10000", "6")   # 60,000
    lr2 = _book(client, h, "Beta", "Raipur", 1, "6000", "7")      # 42,000
    trip = _trip(client, h, [lr1, lr2])
    owner = _owner(client, h)
    url = f"/trips/{trip['id']}"
    # no hire yet: nothing can be paid
    assert client.post(f"{url}/owner-payments", json={"kind": "advance", "amount": "10000", "method": "cash"}, headers=accountant).status_code == 409
    money = client.put(f"{url}/hire", json={"vendor_id": owner["id"], "hire_amount": "85000"}, headers=h).json()
    assert (money["revenue"], money["hire"], money["owed_to_owner"], money["margin"]) == ("102000.00", "85000.00", "85000.00", "17000.00")
    client.post(f"{url}/expenses", json={"kind": "loading_labour", "amount": "1500"}, headers=h)
    paid = client.post(f"{url}/owner-payments", json={"kind": "advance", "amount": "40000", "method": "upi", "reference": "432112345678"}, headers=accountant).json()
    assert (paid["paid_to_owner"], paid["owed_to_owner"], paid["margin"], paid["margin_pct"]) == ("40000.00", "45000.00", "15500.00", 15.2)
    # the hire is fixed once paid; the balance waits for delivery; never pay more than owed
    assert client.put(f"{url}/hire", json={"vendor_id": owner["id"], "hire_amount": "80000"}, headers=h).status_code == 409
    assert client.post(f"{url}/owner-payments", json={"kind": "balance", "amount": "45000", "method": "cash"}, headers=accountant).status_code == 403
    assert client.post(f"{url}/owner-payments", json={"kind": "advance", "amount": "50000", "method": "cash"}, headers=accountant).status_code == 409
    assert client.post(f"{url}/owner-payments", json={"kind": "advance", "amount": "100", "method": "upi"}, headers=accountant).status_code == 422  # no UTR
    # goods short on arrival: deducted from the owner's balance
    client.post(f"{url}/stops/RAIPUR/deliver", headers=h)
    deducted = client.post(f"{url}/deductions", json={"amount": "2000", "reason": "shortage", "note": "2 bundles short at Raipur"}, headers=h).json()
    assert (deducted["owed_to_owner"], deducted["margin"]) == ("43000.00", "17500.00")
    assert client.get("/payables", headers=accountant).json()["total_owed"] == "43000.00"
    settled = client.post(f"{url}/owner-payments", json={"kind": "balance", "amount": "43000", "method": "cash"}, headers=accountant).json()
    assert settled["owed_to_owner"] == "0.00"
    # a mistaken payment is reversed with a reason, never deleted
    assert client.post(f"{url}/owner-payments", json={"kind": "reversal", "amount": "1000", "method": "cash"}, headers=accountant).status_code == 422
    reversed_ = client.post(f"{url}/owner-payments", json={"kind": "reversal", "amount": "1000", "method": "cash", "note": "Counted twice"}, headers=accountant).json()
    assert reversed_["owed_to_owner"] == "1000.00" and [p["kind"] for p in reversed_["payments"]] == ["advance", "balance", "reversal"]

    profit = client.get("/analytics/trip_profit", params=_period(), headers=h).json()
    assert (profit["revenue"], profit["hire"], profit["margin"], profit["hire_share_pct"]) == ("102000.00", "85000.00", "17500.00", 83.3)
    assert profit["by_destination"][0]["destination"] == "RAIPUR"
    finance = client.get("/analytics/finance", params={"period": "this_month"}, headers=h).json()
    assert (finance["totals"]["truck_hire"], finance["totals"]["trip_margin"]) == ("83000.00", "17500.00")
    owners = client.get("/analytics/vendors", params=_period(), headers=h).json()["rows"]
    assert (owners[0]["vendor"], owners[0]["trips"], owners[0]["hire_share_pct"], owners[0]["owed_now"]) == ("Ramesh Roadlines", 1, 83.3, "1000.00")


def test_losing_trips_are_flagged(client, admin):
    h = bearer(admin)
    lr = _book(client, h, "Alpha", "Raipur", 1, "1000", "5")  # 5,000 on a whole truck
    trip = _trip(client, h, [lr])
    client.put(f"/trips/{trip['id']}/hire", json={"vendor_id": _owner(client, h)["id"], "hire_amount": "60000"}, headers=h)
    _trip_without_hire = _trip(client, h, [_book(client, h, "Beta", "Raipur", 1, "100", "5")])
    insights = {i["title"]: i for i in client.get("/analytics/insights", params=_period(), headers=h).json()}
    assert "1 trip(s) lost money" in insights and insights["1 trip(s) lost money"]["severity"] == "high"
    assert "1 trip(s) have no hire recorded" in insights
    assert _trip_without_hire["trip_no"] == 2


def test_quotes_from_truck_owners_are_compared_revised_and_awarded(client, admin):
    h = bearer(admin)
    outbox = app.dependency_overrides[get_outbox]()
    a, b, c = _owner(client, h, "Asha Transport", "9825000001"), _owner(client, h, "Bharat Carriers", "9825000002"), _owner(client, h, "Chetan Logistics", "9825000003")
    rfq = client.post("/rfqs", json={"origin": "Rajkot", "destination": "Raipur", "weight_kg": "16000", "truck_type": "32 ft", "needed_on": str(today() + dt.timedelta(days=1)),
                                      "vendor_ids": [a["id"], b["id"], c["id"]]}, headers=h).json()
    assert rfq["rfq_number"] == 1 and len(outbox.whatsapps) == 3 and "RAJKOT to RAIPUR, 16,000 kg, 32 ft" in outbox.whatsapps[0][1]
    quote = lambda vendor, amount: client.post(f"/rfqs/{rfq['id']}/quotes", json={"vendor_id": vendor["id"], "amount": amount}, headers=h).json()
    quote(a, "90000")
    quote(b, "86000")
    after = quote(a, "84000")  # Asha comes down: a second round
    assert [(q["vendor_name"], q["amount"], q["rank"]) for q in after["quotes"]] == [("Asha Transport", "84000.00", 1), ("Bharat Carriers", "86000.00", 2)]
    assert after["quotes"][0]["revisions"] == ["90000.00"] and after["not_responded"] == ["Chetan Logistics"]
    reminded = client.post(f"/rfqs/{rfq['id']}/remind", headers=h)
    assert reminded.status_code == 200 and len(outbox.whatsapps) == 4
    client.post(f"/rfqs/{rfq['id']}/remind", headers=h)
    assert len(outbox.whatsapps) == 4  # not again within two hours
    first_a = next(q for q in after["quotes"] if q["vendor_name"] == "Asha Transport")
    awarded = client.post(f"/rfqs/{rfq['id']}/award", json={"quote_id": first_a["id"]}, headers=h).json()
    assert awarded["status"] == "awarded"
    assert client.post(f"/rfqs/{rfq['id']}/quotes", json={"vendor_id": c["id"], "amount": "70000"}, headers=h).status_code == 409
    # the trip's hire must match the award
    trip = _trip(client, h, [_book(client, h, "Alpha", "Raipur", 0, "16000", "6")])
    wrong = client.put(f"/trips/{trip['id']}/hire", json={"vendor_id": b["id"], "hire_amount": "86000", "rfq_id": rfq["id"]}, headers=h)
    assert wrong.status_code == 409
    assert client.put(f"/trips/{trip['id']}/hire", json={"vendor_id": a["id"], "hire_amount": "84000", "rfq_id": rfq["id"]}, headers=h).status_code == 200
    summary = client.get("/analytics/rfqs", params=_period(), headers=h).json()
    assert (summary["requests"], summary["awarded"], summary["response_rate_pct"], summary["saved_vs_highest"], summary["saved_by_revisions"]) == (1, 1, 66.7, "2000.00", "6000.00")
    owners = {r["vendor"]: r for r in client.get("/analytics/vendors", params=_period(), headers=h).json()["rows"]}
    assert (owners["Asha Transport"]["quotes_won"], owners["Bharat Carriers"]["win_rate_pct"]) == (1, 0.0)


def test_contracts_set_rates_and_show_who_is_off_them(client, admin):
    h = bearer(admin)
    manager = bearer(add_staff(client, admin, "m@shree.example", "manager"))
    body = {"party_name": "Alpha", "starts_on": str(today() - dt.timedelta(days=20)), "ends_on": str(today() + dt.timedelta(days=10)),
            "terms": "Monthly billing", "rates": [{"destination": "Raipur", "basis": "per_kg", "rate": "5"}]}
    assert client.post("/contracts", json=body, headers=manager).status_code == 403  # rates are the owner's
    contract = client.post("/contracts", json=body, headers=h).json()
    assert (contract["status"], contract["days_left"]) == ("expiring", 10)
    assert client.post("/contracts", json={**body, "starts_on": str(today())}, headers=h).status_code == 409  # overlaps
    rate = client.get("/contracts/rate", params={"party": "alpha", "destination": "raipur"}, headers=h).json()
    assert (rate["basis"], rate["rate"]) == ("per_kg", "5.00")
    assert client.get("/contracts/rate", params={"party": "Alpha", "destination": "Surat"}, headers=h).json() is None
    _book(client, h, "Alpha", "Raipur", 5, "100", "5")
    off = _book(client, h, "Alpha", "Raipur", 3, "100", "4.5")
    rows = client.get("/analytics/contracts", params=_period(), headers=h).json()["rows"]
    assert (rows[0]["lrs"], rows[0]["on_rate"], [o["lr_number"] for o in rows[0]["off_rate"]]) == (2, 1, [off["lr_number"]])
    insights = [i["title"] for i in client.get("/analytics/insights", params=_period(), headers=h).json()]
    assert "Alpha's contract ends in 10 days" in insights and "1 LR(s) for Alpha off the agreed rate" in insights


def test_delays_are_judged_against_the_usual_transit_time(client, admin):
    h = bearer(admin)
    assert client.put("/transit-times", json=[{"destination": "Raipur", "days_min": 4, "days_max": 5}], headers=h).status_code == 200
    assert client.put("/transit-times", json=[{"destination": "Raipur", "days_min": 5, "days_max": 4}], headers=h).status_code == 422
    quick, slow = _book(client, h, "Alpha", "Raipur", 9, "100", "5"), _book(client, h, "Beta", "Raipur", 9, "100", "5")
    for lr, days in ((quick, 4), (slow, 7)):
        trip = _trip(client, h, [lr])
        client.post(f"/trips/{trip['id']}/stops/RAIPUR/deliver", headers=h)
        with owner_engine.begin() as conn:
            conn.execute(text("UPDATE trip SET dispatched_at = now() - make_interval(days => :d) WHERE id = :t"), {"d": days + 1, "t": trip["id"]})
            conn.execute(text("UPDATE dispatch_line SET delivered_at = now() - interval '1 day' WHERE trip_id = :t"), {"t": trip["id"]})
    ex = client.get("/analytics/execution", params=_period(), headers=h).json()
    assert [(d["lr_number"], d["transit_days"], d["lane_median_days"]) for d in ex["delayed"]] == [(slow["lr_number"], 7.0, 5.0)]
    assert ex["on_time_pct"] == 50.0
    assert client.get("/transit-times", headers=h).json() == [{"destination": "RAIPUR", "days_min": 4, "days_max": 5}]

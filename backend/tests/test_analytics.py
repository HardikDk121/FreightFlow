"""Analytics are computed from the records: these tests build a small business and check the figures."""

import datetime as dt
import io
import json

import openpyxl
from sqlalchemy import text

from app.clock import today
from app.main import app
from app.notify import get_outbox
from tests.conftest import add_staff, bearer, owner_engine
from tests.test_branches import _staff
from tests.test_dispatch import _lr, _truck
from tests.test_payments import _receipt, _visit

SIGNATURE = [[[1, 1], [5, 9], [12, 4], [20, 15], [26, 6]], [[30, 2], [34, 12], [40, 5], [46, 14]]]
PAN = {"consignor_gstin": None, "consignor_pan": "AABCR4141H", "consignee_pan": "AWCPP8803A", "consignee_gstin": None}


def _book(client, h, customer, to_city, days_ago, weight, rate, **extra):
    """A TBB LR charged per kg, for `customer` as consignor (the payer on TBB)."""
    freight = f"{float(weight) * float(rate):.2f}"
    return _lr(client, h, freight_by="TBB", consignor_name=customer, to_city=to_city, days_ago=days_ago, weight=weight,
               rate=rate, freight=freight, st_charges="0", charge_basis="per_kg", **PAN, **extra)


def _period(days=30):
    return {"date_from": str(today() - dt.timedelta(days=days - 1)), "date_to": str(today())}


def test_overview_customers_and_lanes_add_up(client, admin):
    h = bearer(admin)
    a1 = _book(client, h, "Alpha", "Raipur", 5, "100", "5")    # 500
    _book(client, h, "Alpha", "Raipur", 3, "200", "5")         # 1000
    _book(client, h, "Beta", "Surat", 2, "100", "3")           # 300
    _book(client, h, "Beta", "Surat", 40, "100", "3")          # outside the 30 days: previous period
    _visit(client, add_staff(client, admin, "r@shree.example", "collector"), _receipt(client, admin, a1), "paid", method="cash", amount="500")

    kpis = {k["key"]: k for k in client.get("/analytics/overview", params=_period(), headers=h).json()["kpis"]}
    assert (kpis["lrs"]["value"], kpis["revenue"]["value"], kpis["weight"]["value"]) == (3, 1800.0, 400.0)
    assert (kpis["collected"]["value"], kpis["outstanding"]["value"], kpis["collection_rate"]["value"]) == (500.0, 1300.0, 27.8)
    assert (kpis["revenue"]["previous"], kpis["revenue"]["change_pct"], kpis["revenue_per_kg"]["value"]) == (300.0, 500.0, 4.5)
    assert kpis["median_days_to_payment"]["value"] == 5.0  # booked 5 days ago, paid today

    customers = client.get("/analytics/customers", params=_period(), headers=h).json()
    rows = {r["customer"]: r for r in customers["rows"]}
    assert (rows["Alpha"]["lrs"], rows["Alpha"]["revenue"], rows["Alpha"]["share_pct"], rows["Alpha"]["outstanding"]) == (2, "1500.00", 83.3, "1000.00")
    assert (rows["Beta"]["previous_revenue"], rows["Beta"]["growth_pct"]) == ("300.00", 0.0)
    assert rows["Alpha"]["avg_days_between_bookings"] == 2.0
    assert "Grouped by payer" in customers["basis"]

    lanes = {(r["origin"], r["destination"]): r for r in client.get("/analytics/lanes", params=_period(), headers=h).json()["rows"]}
    assert lanes[("RAJKOT", "RAIPUR")]["revenue"] == "1500.00" and lanes[("RAJKOT", "SURAT")]["lrs"] == 1

    # filters narrow every figure
    only_beta = {k["key"]: k["value"] for k in client.get("/analytics/overview", params={**_period(), "customer": "beta"}, headers=h).json()["kpis"]}
    assert (only_beta["lrs"], only_beta["revenue"]) == (1, 300.0)
    assert client.get("/analytics/overview", params={"date_from": "2026-11-10", "date_to": "2026-11-01"}, headers=h).json()["error"]["code"] == "bad_filters"


def test_trend_buckets_every_period_including_empty_ones(client, admin):
    h = bearer(admin)
    _book(client, h, "Alpha", "Raipur", 2, "100", "5")
    _book(client, h, "Alpha", "Raipur", 0, "100", "5")
    trend = client.get("/analytics/trend", params={**_period(7), "grain": "day"}, headers=h).json()
    assert len(trend["points"]) == 7
    by_day = {p["period"]: p for p in trend["points"]}
    assert by_day[str(today())]["revenue"] == "500.00" and by_day[str(today() - dt.timedelta(days=1))]["lrs"] == 0
    months = client.get("/analytics/trend", params={"period": "this_year", "grain": "month"}, headers=h).json()["points"]
    assert len(months) == today().month


def test_rates_find_unusual_freight_on_a_lane(client, admin):
    h = bearer(admin)
    for days, rate in ((1, "5"), (2, "5.2"), (3, "4.9"), (4, "5.1"), (5, "5"), (6, "1.5")):
        _book(client, h, "Alpha", "Raipur", days, "100", rate)
    rates = client.get("/analytics/rates", params={**_period(), "destination": "Raipur"}, headers=h).json()
    lane = rates["lanes"][0]
    assert (lane["unit"], lane["samples"], lane["median"], lane["minimum"]) == ("per_kg", 6, 5.0, 1.5)
    assert [(o["rate"], o["direction"]) for o in rates["outliers"]] == [(1.5, "low")]
    assert len(rates["history"]) >= 1
    insights = client.get("/analytics/insights", params=_period(), headers=h).json()
    assert any("unusual rates" in i["title"] for i in insights)


def test_execution_tracks_each_stage_and_late_trips(client, admin):
    h = bearer(admin)
    branch = client.post("/branches", json={"name": "Raipur", "cities": ["Raipur"]}, headers=h).json()
    waiting = _book(client, h, "Alpha", "Raipur", 2, "100", "5")
    sent = _book(client, h, "Alpha", "Raipur", 3, "100", "5")
    trip = client.post("/trips", json={"truck_id": _truck(client, h), "stops": ["Raipur"], "lines": [{"lr_id": sent["id"], "packages": sent["packages"]}]}, headers=h).json()
    client.post(f"/trips/{trip['id']}/stops/RAIPUR/deliver", headers=h)
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE trip SET dispatched_at = now() - interval '2 days'"))
        conn.execute(text("UPDATE dispatch_line SET delivered_at = now() - interval '1 day'"))
    ex = client.get("/analytics/execution", params=_period(), headers=h).json()
    assert ex["stages"] == {"awaiting_dispatch": 1, "in_transit": 0, "awaiting_delivery": 1, "delivered": 0}
    durations = {d["stage"]: d for d in ex["durations"]}
    assert durations["On the road (dispatch to unloading)"]["median_days"] == 1.0
    assert {p["lr_number"]: p["stage"] for p in ex["pending"]} == {waiting["lr_number"]: "awaiting_dispatch", sent["lr_number"]: "awaiting_delivery"}
    # signing the gate pass moves it to delivered
    gp = client.post("/gate-passes", json={"lr_ids": [sent["id"]]}, headers=h).json()
    proof = {"delivered_at": dt.datetime.now(dt.UTC).isoformat(), "receiver_name": "Mahesh", "signature": SIGNATURE}
    client.post(f"/gate-passes/{gp['id']}/delivery", data={"proof": json.dumps(proof)}, headers=h)
    assert client.get("/analytics/execution", params=_period(), headers=h).json()["stages"]["delivered"] == 1
    fleet = client.get("/analytics/fleet", params=_period(), headers=h).json()["rows"]
    assert (fleet[0]["trips"], fleet[0]["lrs"], fleet[0]["weight_carried"]) == (1, 1, "100.00")
    branches = {b["branch"]: b for b in client.get("/analytics/branches", params=_period(), headers=h).json()["rows"]}
    assert branches["Raipur"]["lrs_delivered"] == 1 and branches["Head office"]["lrs_booked"] == 2
    assert branch["name"] == "Raipur"


def test_finance_months_by_payment_method(client, admin):
    h = bearer(admin)
    lr = _book(client, h, "Alpha", "Raipur", 1, "100", "5")
    _visit(client, add_staff(client, admin, "r@shree.example", "collector"), _receipt(client, admin, lr), "part_paid", method="upi", amount="200", utr="432112345678")
    finance = client.get("/analytics/finance", params={"period": "this_month"}, headers=h).json()
    assert (finance["totals"]["revenue_booked"], finance["totals"]["collected_upi"], finance["totals"]["confirmed_by_bank"]) == ("500.00", "200.00", "0")
    assert "truck owner" in finance["expenses_note"]
    collector = add_staff(client, admin, "c2@shree.example", "collector")
    assert client.get("/analytics/finance", headers=bearer(collector)).status_code == 403


def test_custom_reports_and_exports(client, admin):
    h = bearer(admin)
    _book(client, h, "Alpha", "Raipur", 1, "100", "5")
    _book(client, h, "Beta", "Surat", 1, "50", "4")
    table = client.post("/analytics/custom", params=_period(), json={"group_by": "destination", "measures": ["lrs", "revenue", "weight"], "sort_by": "Revenue"}, headers=h).json()
    assert table["columns"] == ["Destination", "LRs", "Revenue", "Weight (kg)"]
    assert table["rows"] == [["RAIPUR", 1, 500.0, 100.0], ["SURAT", 1, 200.0, 50.0]]
    listed = client.post("/analytics/custom", params=_period(), json={"group_by": "none"}, headers=h).json()
    assert len(listed["rows"]) == 2 and listed["columns"][0] == "LR"
    bad = client.post("/analytics/custom", params=_period(), json={"group_by": "password_hash", "measures": ["lrs"]}, headers=h)
    assert bad.status_code == 422
    sheet = client.get("/analytics/customers/export", params={**_period(), "format": "xlsx"}, headers=h)
    book = openpyxl.load_workbook(io.BytesIO(sheet.content))
    assert book.sheetnames == ["Customers"] and book["Customers"]["A5"].value in ("Alpha", "Beta")
    pdf = client.get("/analytics/customers/export", params={**_period(), "format": "pdf"}, headers=h)
    assert pdf.content.startswith(b"%PDF")
    custom_xlsx = client.post("/analytics/custom/export", params={**_period(), "format": "xlsx"}, json={"group_by": "payer", "measures": ["revenue"]}, headers=h)
    assert custom_xlsx.status_code == 200


def test_scheduled_reports_go_by_email_with_the_authors_branch_only(client, admin):
    h = bearer(admin)
    outbox = app.dependency_overrides[get_outbox]()
    raipur = client.post("/branches", json={"name": "Raipur", "cities": ["Raipur"]}, headers=h).json()
    _book(client, h, "Alpha", "Raipur", 1, "100", "5")
    _book(client, h, "Beta", "Surat", 1, "100", "5")
    manager = bearer(_staff(client, admin, "m@shree.example", "manager", raipur["id"]))
    assert client.post("/analytics/saved", json={"name": "Daily customers", "analysis": "customers", "schedule": "daily"}, headers=manager).status_code == 422
    saved = client.post("/analytics/saved", json={"name": "Daily customers", "analysis": "customers", "filters": {"period": "last_7_days"},
                                                   "schedule": "daily", "recipients": ["m@shree.example"]}, headers=manager)
    assert saved.status_code == 201
    assert client.post("/analytics/saved", json={"name": "daily customers", "analysis": "lanes"}, headers=manager).status_code == 409
    from app.jobs import daily

    assert daily(outbox)["reports"] == 1
    name, content, _ = outbox.attachments[-1]
    sheet = openpyxl.load_workbook(io.BytesIO(content))["Customers"]
    customers = [sheet.cell(row=r, column=1).value for r in range(5, sheet.max_row + 1)]
    assert customers == ["Alpha"]  # the Raipur manager's report holds Raipur's customers only
    assert daily(outbox)["reports"] == 0  # once a day
    assert [r["name"] for r in client.get("/analytics/saved/list", headers=manager).json()] == ["Daily customers"]


def test_who_can_see_analytics(client, admin):
    clerk = add_staff(client, admin, "c@shree.example", "clerk")
    accountant = add_staff(client, admin, "a@shree.example", "accountant")
    assert client.get("/analytics/overview", headers=bearer(clerk)).status_code == 403
    assert client.get("/analytics/overview", headers=bearer(accountant)).status_code == 200
    options = client.get("/analytics/options", headers=bearer(admin)).json()
    assert options == {"customers": [], "origins": [], "destinations": []}

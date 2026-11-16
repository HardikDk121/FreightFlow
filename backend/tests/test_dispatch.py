import datetime as dt

from app.clock import today
from tests.conftest import add_staff, bearer, register
from tests.test_lr import NEW_LR

TRUCK = {"vehicle_number": "GJ03CW0620", "inner_length_cm": 500, "inner_width_cm": 200, "inner_height_cm": 200, "payload_kg": 3000, "model_year": 2022, "insurance_expiry": "2099-01-01", "fitness_expiry": "2099-01-01"}


def _item(client, h, name, dims, weight):
    body = {"name": name, "length_cm": dims[0], "width_cm": dims[1], "height_cm": dims[2], "unit_weight_kg": weight}
    return client.post("/item-types", json=body, headers=h).json()["id"]


def _lr(client, h, *, days_ago=0, **changes):
    body = {**NEW_LR, "to_city": "Surat", "lr_date": str(today() - dt.timedelta(days=days_ago)), **changes}
    response = client.post("/lrs", json=body, headers=h)
    assert response.status_code == 201, response.text
    return response.json()


def _truck(client, h, number="GJ03CW0620"):
    return client.post("/trucks", json={**TRUCK, "vehicle_number": number}, headers=h).json()["id"]


def test_pending_lists_waiting_goods_oldest_first(client, admin):
    h = bearer(admin)
    _lr(client, h, days_ago=1, packages=10)
    _lr(client, h, days_ago=3, packages=50)
    _lr(client, h, days_ago=2, packages=4, to_city="Delhi")
    cancelled = _lr(client, h, days_ago=9, packages=1)
    client.post(f"/lrs/{cancelled['id']}/cancel", json={"reason": "test"}, headers=h)

    surat = client.get("/pending/lrs", params={"destination": "surat"}, headers=h).json()
    assert [(x["pending"], x["days_waiting"]) for x in surat] == [(50, 3), (10, 1)]
    older = client.get("/pending/lrs", params={"older_than_days": 1}, headers=h).json()
    assert [x["to_city"] for x in older] == ["Surat", "Delhi"]
    groups = client.get("/pending", headers=h).json()
    assert [(g["to_city"], g["lr_count"], g["packages"], g["days_waiting"]) for g in groups] == [
        ("SURAT", 2, 60, 3),
        ("DELHI", 1, 4, 2),
    ]


def test_plan_matches_the_proposals_worked_example(client, admin):
    h = bearer(admin)
    truck = _truck(client, h)
    cases = [(4, 40, (60, 40, 40), 18), (3, 24, (100, 50, 50), 30), (2, 50, (50, 50, 40), 20), (1, 30, (60, 60, 50), 20)]
    for days_ago, packages, dims, weight in cases:
        _lr(client, h, days_ago=days_ago, packages=packages, item_type_id=_item(client, h, f"Item {days_ago}", dims, weight))
    unsized = _lr(client, h, days_ago=0, packages=5)

    plan = client.post("/trips/plan", json={"truck_id": truck, "destination": "SURAT"}, headers=h)
    assert plan.status_code == 200, plan.text
    body = plan.json()
    assert [line["load"] for line in body["lines"]] == [40, 24, 50, 12]
    assert (body["volume_used_pct"], body["payload_used_pct"]) == (85, 89)
    assert [x["lr_number"] for x in body["unsized"]] == [unsized["lr_number"]]


def test_partial_dispatch_keeps_the_rest_pending(client, admin):
    h = bearer(admin)
    truck = _truck(client, h)
    lr = _lr(client, h, packages=30)
    trip = client.post(
        "/trips",
        json={"truck_id": truck, "destination": "Surat", "driver_name": "Ramesh", "lines": [{"lr_id": lr["id"], "packages": 12}]},
        headers=h,
    )
    assert trip.status_code == 201, trip.text
    assert trip.json()["status"] == "dispatched" and trip.json()["lines"][0]["packages"] == 12
    assert client.get("/pending/lrs", headers=h).json()[0]["pending"] == 18

    second_truck = _truck(client, h, "GJ03AB0001")
    too_many = client.post(
        "/trips", json={"truck_id": second_truck, "destination": "Surat", "lines": [{"lr_id": lr["id"], "packages": 19}]}, headers=h
    )
    assert too_many.status_code == 409 and "only 18" in too_many.json()["error"]["message"]
    rest = client.post(
        "/trips", json={"truck_id": second_truck, "destination": "Surat", "lines": [{"lr_id": lr["id"], "packages": 18}]}, headers=h
    )
    assert rest.status_code == 201
    assert client.get("/pending/lrs", headers=h).json() == []
    # dispatched LRs can no longer be cancelled
    assert client.post(f"/lrs/{lr['id']}/cancel", json={"reason": "late"}, headers=h).status_code == 409


def test_truck_cannot_be_on_two_open_trips_and_delivery_frees_it(client, admin):
    h = bearer(admin)
    truck = _truck(client, h)
    first, second = _lr(client, h, packages=5), _lr(client, h, packages=5)
    trip = client.post(
        "/trips", json={"truck_id": truck, "destination": "Surat", "lines": [{"lr_id": first["id"], "packages": 5}]}, headers=h
    ).json()
    body = {"truck_id": truck, "destination": "Surat", "lines": [{"lr_id": second["id"], "packages": 5}]}
    busy = client.post("/trips", json=body, headers=h)
    assert busy.status_code == 409 and "already out" in busy.json()["error"]["message"]
    # the refused trip dispatched nothing
    assert client.get("/pending/lrs", headers=h).json()[0]["pending"] == 5

    line = trip["lines"][0]["id"]
    delivered = client.post(f"/trips/{trip['id']}/lines/{line}/deliver", headers=h)
    assert delivered.status_code == 200 and delivered.json()["status"] == "completed"
    assert client.post(f"/trips/{trip['id']}/lines/{line}/deliver", headers=h).status_code == 409
    assert client.post("/trips", json=body, headers=h).status_code == 201
    assert [t["status"] for t in client.get("/trips", headers=h).json()] == ["dispatched", "completed"]
    assert len(client.get("/trips", params={"status": "completed"}, headers=h).json()) == 1


def test_dispatch_rules(client, admin):
    h = bearer(admin)
    truck = _truck(client, h)
    lr = _lr(client, h, packages=5)
    line = {"lr_id": lr["id"], "packages": 1}
    clerk = add_staff(client, admin, "clerk@shree.example", "clerk")
    assert client.post("/trips", json={"truck_id": truck, "destination": "Surat", "lines": [line]}, headers=bearer(clerk)).status_code == 403
    assert client.post("/trips", json={"truck_id": truck, "destination": "Surat", "lines": [line, line]}, headers=h).status_code == 422
    assert client.post("/trips", json={"truck_id": truck, "destination": "Surat", "lines": []}, headers=h).status_code == 422

    other = register(client, "Other Transport", "o@o.example")
    other_truck = _truck(client, bearer(other))
    # another company's LR or truck is simply not found
    assert client.post("/trips", json={"truck_id": other_truck, "destination": "Surat", "lines": [line]}, headers=h).status_code == 404
    stolen = client.post("/trips", json={"truck_id": other_truck, "destination": "Surat", "lines": [line]}, headers=bearer(other))
    assert stolen.status_code == 404
    assert client.get("/pending", headers=bearer(other)).json() == []
    assert client.post("/lrs", json={**NEW_LR, "item_type_id": _item(client, h, "Mine", (1, 1, 1), 1)}, headers=bearer(other)).status_code == 404


def test_dashboard_counts(client, admin):
    h = bearer(admin)
    truck = _truck(client, h)
    lr = _lr(client, h, packages=8)
    _lr(client, h, days_ago=2, packages=2, to_city="Delhi")
    client.post("/trips", json={"truck_id": truck, "destination": "Surat", "lines": [{"lr_id": lr["id"], "packages": 3}]}, headers=h)
    board = client.get("/dashboard", headers=h).json()
    assert (board["lrs_today"], board["pending_packages"], board["pending_lrs"], board["trips_on_road"]) == (1, 7, 2, 1)
    assert [g["to_city"] for g in board["pending_by_destination"]] == ["DELHI", "SURAT"]

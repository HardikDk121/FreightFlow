from tests.conftest import add_staff, bearer
from tests.test_dispatch import _item, _lr, _truck

ROUTE = ["DHAMTARI", "JAGDALPUR"]


def _send(client, h, truck, stops, *lines):
    return client.post(
        "/trips", json={"truck_id": truck, "stops": stops, "lines": [{"lr_id": lr["id"], "packages": n} for lr, n in lines]}, headers=h
    )


def _truck_row(client, h, truck_id):
    return client.get(f"/trucks/{truck_id}", headers=h).json()


def test_a_trip_drops_at_each_stop_and_frees_the_truck_only_at_the_last(client, admin):
    h = bearer(admin)
    truck = _truck(client, h)
    mid_a = _lr(client, h, packages=3, to_city="Dhamtari")
    mid_b = _lr(client, h, packages=2, to_city="dhamtari", consignee_name="Kaveri Traders")
    final = _lr(client, h, packages=4, to_city="Jagdalpur")
    elsewhere = _lr(client, h, packages=1, to_city="Ambikapur")

    wrong = _send(client, h, truck, ROUTE, (elsewhere, 1))
    assert wrong.status_code == 409 and "not a stop on this trip" in wrong.json()["error"]["message"]
    assert client.post("/trips", json={"truck_id": truck, "stops": ["Dhamtari", "dhamtari"], "lines": [{"lr_id": final["id"], "packages": 1}]}, headers=h).status_code == 422

    trip = _send(client, h, truck, ["Dhamtari", "Jagdalpur"], (mid_a, 3), (mid_b, 2), (final, 4)).json()
    assert (trip["destination"], trip["progress"], trip["next_stop"]) == ("JAGDALPUR", "in_transit", "DHAMTARI")
    assert trip["stops"] == [
        {"city": "DHAMTARI", "lr_count": 2, "delivered_count": 0},
        {"city": "JAGDALPUR", "lr_count": 1, "delivered_count": 0},
    ]

    # the truck unloads at the midpoint: only those LRs are delivered, and the trip stays open
    at_midpoint = client.post(f"/trips/{trip['id']}/stops/dhamtari/deliver", headers=h).json()
    assert (at_midpoint["status"], at_midpoint["progress"], at_midpoint["next_stop"]) == ("dispatched", "partially_delivered", "JAGDALPUR")
    assert [line["delivered_at"] is not None for line in at_midpoint["lines"]] == [True, True, False]
    assert client.post(f"/trips/{trip['id']}/stops/dhamtari/deliver", headers=h).status_code == 409
    # it still carries goods for the last stop, so it cannot be given another trip
    busy = _send(client, h, truck, ["AMBIKAPUR"], (elsewhere, 1))
    assert busy.status_code == 409 and "still on a trip" in busy.json()["error"]["message"]
    assert _truck_row(client, h, truck)["current_station"] is None

    done = client.post(f"/trips/{trip['id']}/stops/JAGDALPUR/deliver", headers=h).json()
    assert (done["status"], done["progress"], done["next_stop"]) == ("completed", "delivered", None)
    assert _truck_row(client, h, truck)["current_station"] == "JAGDALPUR"
    assert _send(client, h, truck, ["AMBIKAPUR"], (elsewhere, 1)).status_code == 201

    # undoing the last drop puts the first trip back on the road only if the truck has not left again
    last_line = done["lines"][-1]["id"]
    assert client.post(f"/trips/{trip['id']}/lines/{last_line}/undo-delivery", headers=h).status_code == 409


def test_suggestions_group_stations_on_one_route_onto_one_truck(client, admin):
    h = bearer(admin)
    assert client.get("/trips/suggestions", headers=h).json() == []
    client.post("/routes", json={"name": "Bastar run", "stops": ["Raipur", "Dhamtari", "Jagdalpur"]}, headers=h)
    small = _truck(client, h, "GJ03AA0001")
    client.patch(f"/trucks/{small}", json={"payload_kg": 1000, "current_station": "Rajkot"}, headers=h)
    _truck(client, h, "GJ03BB0002")
    carton = _item(client, h, "Carton", (50, 50, 40), 20)

    _lr(client, h, days_ago=4, packages=30, to_city="Jagdalpur", item_type_id=carton)  # 600 kg
    _lr(client, h, days_ago=2, packages=30, to_city="Dhamtari", item_type_id=carton)  # 600 kg
    _lr(client, h, days_ago=1, packages=10, to_city="Ambikapur")  # no package type: 100 kg by weight

    bastar, ambikapur = client.get("/trips/suggestions", headers=h).json()
    # 1200 kg for two stations on one route: too much for the small truck, so the big one takes both
    assert (bastar["route_name"], bastar["stops"], bastar["vehicle_number"]) == ("Bastar run", ["DHAMTARI", "JAGDALPUR"], "GJ03BB0002")
    assert (bastar["packages_loaded"], bastar["packages_pending"], bastar["oldest_days_waiting"]) == (60, 60, 4)
    assert sorted(line["to_city"] for line in bastar["plan"]["lines"]) == ["DHAMTARI", "JAGDALPUR"]
    assert bastar["reason"].startswith("Takes all packages for DHAMTARI and JAGDALPUR in one run")
    # the leftover city gets the truck that is still free, and says where that truck stands
    assert (ambikapur["route_name"], ambikapur["stops"], ambikapur["vehicle_number"], ambikapur["truck_location"]) == (
        None, ["AMBIKAPUR"], "GJ03AA0001", "RAJKOT")
    assert ambikapur["packages_loaded"] == 10 and len(ambikapur["plan"]["weight_only"]) == 1

    # with both trucks out, the next group has nothing to ride on
    for s in (bastar, ambikapur):
        lines = [{"lr_id": line["lr_id"], "packages": line["load"]} for line in s["plan"]["lines"]]
        assert client.post("/trips", json={"truck_id": s["truck_id"], "stops": s["stops"], "lines": lines}, headers=h).status_code == 201
    _lr(client, h, packages=5, to_city="Raipur")
    stranded = client.get("/trips/suggestions", headers=h).json()
    assert len(stranded) == 1 and stranded[0]["truck_id"] is None and "No free truck" in stranded[0]["reason"]

    clerk = add_staff(client, admin, "clerk@shree.example", "clerk")
    assert client.get("/trips/suggestions", headers=bearer(clerk)).status_code == 403


def test_pending_can_be_listed_for_several_stops_at_once(client, admin):
    h = bearer(admin)
    _lr(client, h, packages=1, to_city="Dhamtari")
    _lr(client, h, packages=1, to_city="Jagdalpur")
    _lr(client, h, packages=1, to_city="Raipur")
    both = client.get("/pending/lrs", params={"destination": "Dhamtari, Jagdalpur"}, headers=h).json()
    assert sorted(x["to_city"] for x in both) == ["Dhamtari", "Jagdalpur"]


def test_suggest_a_load_in_the_situations_the_app_meets(client, admin):
    """The planner answers every case with a plan the app can show, never an error it cannot explain."""
    h = bearer(admin)
    truck = _truck(client, h)
    plan = lambda stops: client.post("/trips/plan", json={"truck_id": truck, "stops": stops}, headers=h)
    # nothing waiting: an empty plan, not an error
    empty = plan(["Raipur"]).json()
    assert (empty["lines"], empty["weight_only"], empty["unsized"], empty["too_big"]) == ([], [], [], [])
    # stops typed in any case match LRs saved in any case
    _lr(client, h, packages=3, to_city="raipur")
    assert [line["load"] for line in plan(["RAIPUR"]).json()["lines"]] == [3]
    assert [line["load"] for line in plan(["Raipur"]).json()["lines"]] == [3]
    # a deactivated truck is refused clearly
    client.patch(f"/trucks/{truck}", json={"is_active": False}, headers=h)
    gone = plan(["Raipur"])
    assert gone.status_code == 404 and gone.json()["error"]["message"] == "Truck not found."
    # repeated stops are refused before planning
    client.patch(f"/trucks/{truck}", json={"is_active": True}, headers=h)
    assert plan(["Raipur", "RAIPUR"]).status_code == 422

from decimal import Decimal as D

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.planner.planner import Cargo, TruckSpec, first_overload
from tests.conftest import add_staff, bearer, owner_engine, register
from tests.test_dispatch import _lr, _truck
from tests.test_tenancy import SCOPE, app_engine

SIGNATURE = [[[1, 1], [5, 9], [12, 4], [20, 15], [26, 6]], [[30, 2], [34, 12], [40, 5], [46, 14]]]


def _trip(client, h, stops, *lines, truck=None):
    response = client.post(
        "/trips",
        json={"truck_id": truck or _truck(client, h), "stops": stops, "driver_name": "Ramesh",
              "lines": [{"lr_id": lr["id"], "packages": n} for lr, n in lines]},
        headers=h,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _add(client, tokens, trip, loaded_at, *lines, before=None):
    body = {"loaded_at": loaded_at, "lines": [{"lr_id": lr["id"], "packages": n} for lr, n in lines]}
    if before:
        body["insert_before"] = before
    return client.post(f"/trips/{trip['id']}/additions", json=body, headers=bearer(tokens))


def _sign(client, tokens, challan, **body):
    return client.post(
        f"/challans/{challan['id']}/sign", json={"driver_name": "Ramesh", "signature": SIGNATURE, **body}, headers=bearer(tokens)
    )


def test_per_leg_overload_check():
    truck = TruckSpec(D(500), D(200), D(200), D(3000))
    origin_to_last = Cargo(pickup=-1, drop=2, weight_kg=D(2000), volume_cm3=D(0))
    origin_to_first = Cargo(pickup=-1, drop=0, weight_kg=D(900), volume_cm3=D(0))
    # 500 kg added at stop 0, after the 900 kg for stop 0 has come off: fits on every later leg
    assert first_overload(truck, 3, [origin_to_last, origin_to_first, Cargo(0, 2, D(500), D(0))], from_leg=1) is None
    over = first_overload(truck, 3, [origin_to_last, Cargo(0, 1, D(1001), D(0))], from_leg=1)
    assert (over.leg, over.what, over.load, over.limit) == (1, "weight", D(3001), D(3000))
    # only until its own drop: the leg after is fine again
    assert first_overload(truck, 3, [origin_to_last, Cargo(0, 1, D(1001), D(0))], from_leg=2) is None
    bulky = Cargo(0, 2, D(10), D(500) * 200 * 200)  # the whole truck body, beyond the usable share
    assert first_overload(truck, 3, [bulky], from_leg=1).what == "space"


def test_cargo_added_on_the_road_gets_its_own_sealed_challan(client, admin):
    h = bearer(admin)
    clerk = add_staff(client, admin, "clerk@shree.example", "clerk")
    manager = add_staff(client, admin, "manager@shree.example", "manager")
    origin = _lr(client, h, packages=4, to_city="Raipur")
    trip = _trip(client, h, ["Raipur"], (origin, 4))
    assert (trip["trip_no"], trip["lines"][0]["challan_number"], trip["lines"][0]["loaded_at"]) == (1, "CH-1", "RAJKOT")

    # Ahmedabad wants to load 3 packages onto the truck that already left Rajkot
    extra = _lr(client, bearer(clerk), packages=3, to_city="Raipur", from_city="Ahmedabad", consignee_name="Kaveri Traders")
    assert _add(client, clerk, trip, "Ahmedabad", (extra, 3)).json()["error"]["code"] == "stop_needed"
    requested = _add(client, clerk, trip, "Ahmedabad", (extra, 3), before="Raipur")
    assert requested.status_code == 201, requested.text
    challan = requested.json()
    assert (challan["challan_number"], challan["seq"], challan["status"], challan["loaded_at"]) == ("CH-1/S1", 1, "requested", "AHMEDABAD")
    assert challan["lines"] == [
        {"lr_id": extra["id"], "lr_number": extra["lr_number"], "consignee_name": "Kaveri Traders", "to_city": "RAIPUR", "requested": 3, "loaded": None}
    ]
    assert (challan["can_approve"], challan["can_sign"], challan["can_void"]) == (False, False, True)
    # a request moves nothing: the goods are still pending, and the trip is unchanged
    assert client.get("/pending/lrs", headers=h).json()[0]["pending"] == 3
    assert [s["city"] for s in client.get(f"/trips/{trip['id']}", headers=h).json()["stops"]] == ["RAIPUR"]
    assert _sign(client, clerk, challan).status_code == 409

    # only the person who dispatched the trip approves
    for other in (clerk, manager):
        assert client.post(f"/challans/{challan['id']}/approve", headers=bearer(other)).status_code == 403
    approved = client.post(f"/challans/{challan['id']}/approve", headers=h).json()
    assert (approved["status"], approved["approved_by"], approved["can_sign"]) == ("awaiting_driver", "Asha", True)
    assert [s["city"] for s in client.get(f"/trips/{trip['id']}", headers=h).json()["stops"]] == ["AHMEDABAD", "RAIPUR"]
    assert client.post(f"/challans/{challan['id']}/approve", headers=h).status_code == 409

    # the driver counts 2 of the 3 and signs; the shortage is recorded, not edited away
    assert _sign(client, clerk, challan, signature=[[[1, 1], [2, 2]]]).status_code == 422
    assert _sign(client, clerk, challan, counts=[{"lr_id": extra["id"], "packages": 4}]).status_code == 409
    issued = _sign(client, clerk, challan, counts=[{"lr_id": extra["id"], "packages": 2}]).json()
    assert (issued["status"], issued["driver_name"], issued["sealed"]) == ("issued", "Ramesh", True)
    assert issued["shortage_note"] == f"{extra['lr_number']}: 2 of 3 loaded" and issued["lines"][0]["loaded"] == 2
    assert client.get("/pending/lrs", headers=h).json()[0]["pending"] == 1
    lines = {line["lr_number"]: line for line in client.get(f"/trips/{trip['id']}", headers=h).json()["lines"]}
    assert (lines[extra["lr_number"]]["challan_number"], lines[extra["lr_number"]]["loaded_at"], lines[extra["lr_number"]]["packages"]) == ("CH-1/S1", "AHMEDABAD", 2)

    # once issued it cannot be voided or signed again
    assert client.post(f"/challans/{challan['id']}/void", json={"reason": "changed my mind"}, headers=h).status_code == 409
    assert _sign(client, clerk, challan).status_code == 409

    # months later, a search for the parcel leads to the truck, the trip and where it was put on
    found = client.post("/chat", json={"message": f"where is {extra['lr_number']}"}, headers=h).json()["answer"]
    assert "truck GJ03CW0620 to RAIPUR, driver Ramesh" in found and "added at AHMEDABAD on challan CH-1/S1" in found
    sheet = client.get(f"/trips/{trip['id']}/load-sheet.pdf", headers=h)
    assert sheet.status_code == 200

    # delivery works as before; the trip completes when every challan's lines are delivered
    done = client.post(f"/trips/{trip['id']}/stops/Raipur/deliver", headers=h).json()
    assert done["status"] == "completed"
    late = _lr(client, h, packages=1, to_city="Raipur")
    assert _add(client, clerk, trip, "Ahmedabad", (late, 1)).status_code == 409


def test_the_dispatcher_cannot_approve_their_own_request(client, admin):
    h = bearer(admin)
    second_admin = add_staff(client, admin, "boss@shree.example", "admin")
    manager = add_staff(client, admin, "manager@shree.example", "manager")
    trip = _trip(client, h, ["Raipur"], (_lr(client, h, packages=1, to_city="Raipur"), 1))
    own = _add(client, admin, trip, "Ahmedabad", (_lr(client, h, packages=1, to_city="Raipur"), 1), before="Raipur").json()
    assert own["can_approve"] is False
    assert client.post(f"/challans/{own['id']}/approve", headers=h).status_code == 403
    assert client.post(f"/challans/{own['id']}/approve", headers=bearer(manager)).status_code == 403
    assert client.post(f"/challans/{own['id']}/approve", headers=bearer(second_admin)).json()["status"] == "awaiting_driver"


def test_an_addition_is_refused_when_it_would_overload_or_cannot_be_dropped(client, admin):
    h = bearer(admin)
    clerk = add_staff(client, admin, "clerk@shree.example", "clerk")
    heavy = _lr(client, h, packages=1, weight="2900", to_city="Jagdalpur")
    for_dhamtari = _lr(client, h, packages=6, to_city="Dhamtari")
    trip = _trip(client, h, ["Dhamtari", "Jagdalpur"], (heavy, 1), (for_dhamtari, 6))  # 3000 kg payload, 2900 + 100 on board

    too_heavy = _add(client, clerk, trip, "Raipur", (_lr(client, h, packages=1, weight="200", to_city="Jagdalpur"), 1), before="Dhamtari")
    assert too_heavy.status_code == 409 and "Too much weight for truck GJ03CW0620" in too_heavy.json()["error"]["message"]
    off_route = _add(client, clerk, trip, "Raipur", (_lr(client, h, packages=1, to_city="Delhi"), 1), before="Dhamtari")
    assert off_route.status_code == 409 and "not a stop after RAIPUR" in off_route.json()["error"]["message"]
    backwards = _add(client, clerk, trip, "Dhamtari", (for_dhamtari, 1))
    assert backwards.status_code == 409  # goods for Dhamtari cannot be loaded at Dhamtari
    needs_bill = _lr(client, h, packages=1, to_city="Jagdalpur", value="80000", distance_km=300, eway_bill_no=None)
    assert "needs an e-way bill" in _add(client, clerk, trip, "Raipur", (needs_bill, 1), before="Dhamtari").json()["error"]["message"]

    # once the Dhamtari goods are off, there is room; but the truck cannot go back to a stop before it
    client.post(f"/trips/{trip['id']}/stops/Dhamtari/deliver", headers=h)
    small = _lr(client, h, packages=1, weight="50", to_city="Jagdalpur")
    passed = _add(client, clerk, trip, "Raipur", (small, 1), before="Dhamtari")
    assert passed.status_code == 409 and "already reached DHAMTARI" in passed.json()["error"]["message"]
    assert _add(client, clerk, trip, "Dhamtari", (small, 1)).status_code == 201


def test_approver_is_warned_when_added_goods_will_block_unloading(client, admin):
    h = bearer(admin)
    clerk = add_staff(client, admin, "clerk@shree.example", "clerk")
    trip = _trip(client, h, ["Dhamtari", "Jagdalpur"], (_lr(client, h, packages=6, to_city="Dhamtari"), 6))
    through = _lr(client, h, packages=4, to_city="Jagdalpur")
    challan = _add(client, clerk, trip, "Raipur", (through, 4), before="Dhamtari").json()
    assert challan["warnings"] == ["4 of these packages go beyond DHAMTARI and will be in front of 6 packages that unload there."]
    # the approver sees the same warning in their list, before deciding
    assert client.get("/challans/open", headers=h).json()[0]["warnings"] == challan["warnings"]
    assert client.post(f"/challans/{challan['id']}/approve", headers=h).json()["warnings"] == challan["warnings"]


def test_void_keeps_the_number_and_the_e_way_bill_starts_at_sign_off(client, admin):
    h = bearer(admin)
    clerk = add_staff(client, admin, "clerk@shree.example", "clerk")
    stranger = add_staff(client, admin, "other@shree.example", "clerk")
    trip = _trip(client, h, ["Raipur"], (_lr(client, h, packages=1, to_city="Raipur"), 1))
    billed = _lr(client, h, packages=2, to_city="Raipur", value="80000", distance_km=300, eway_bill_no="692194190201")
    assert billed["ewb_status"] == "awaiting_part_b"

    first = _add(client, clerk, trip, "Ahmedabad", (billed, 2), before="Raipur").json()
    assert client.post(f"/challans/{first['id']}/void", json={"reason": "no"}, headers=bearer(clerk)).status_code == 422
    assert client.post(f"/challans/{first['id']}/void", json={"reason": "Wrong truck"}, headers=bearer(stranger)).status_code == 403
    voided = client.post(f"/challans/{first['id']}/void", json={"reason": "Wrong truck"}, headers=bearer(clerk)).json()
    assert (voided["status"], voided["void_reason"]) == ("void", "Wrong truck")
    assert client.post(f"/challans/{first['id']}/approve", headers=h).status_code == 409

    # the voided request keeps S1; the next one is S2
    second = _add(client, clerk, trip, "Ahmedabad", (billed, 2), before="Raipur").json()
    assert second["challan_number"] == "CH-1/S2"
    assert [c["challan_number"] for c in client.get("/challans/open", headers=h).json()] == ["CH-1/S2"]
    assert [c["challan_number"] for c in client.get("/dashboard/admin", headers=h).json()["additions_waiting"]] == ["CH-1/S2"]
    client.post(f"/challans/{second['id']}/approve", headers=h)
    assert client.get(f"/lrs/{billed['id']}", headers=h).json()["ewb_status"] == "awaiting_part_b"
    assert _sign(client, clerk, second).json()["status"] == "issued"
    moving = client.get(f"/lrs/{billed['id']}", headers=h).json()
    assert (moving["ewb_status"], moving["ewb_vehicle_number"]) == ("active", "GJ03CW0620")
    listed = client.get(f"/trips/{trip['id']}/challans", headers=h).json()
    assert [(c["challan_number"], c["status"], c["sealed"]) for c in listed] == [("CH-1", "issued", True), ("CH-1/S1", "void", None), ("CH-1/S2", "issued", True)]


def test_an_issued_challan_cannot_be_altered_and_tampering_shows(client, admin):
    h = bearer(admin)
    lr = _lr(client, h, packages=5, to_city="Raipur")
    trip = _trip(client, h, ["Raipur"], (lr, 5))
    company_id = client.get("/company", headers=h).json()["id"]
    # the API's own database role is not allowed to change what a challan says
    for statement in (
        "UPDATE dispatch_line SET packages = 1",
        "UPDATE challan SET challan_number = 'CH-999'",
        "UPDATE challan SET requested_lines = '[]'",
        "DELETE FROM challan",
    ):
        with app_engine.connect() as conn:
            conn.execute(text(SCOPE), {"c": company_id})
            with pytest.raises(DBAPIError, match="permission denied"):
                conn.execute(text(statement))
            conn.rollback()
    assert client.get(f"/trips/{trip['id']}/challans", headers=h).json()[0]["sealed"] is True
    # someone with direct database access changes a line: the seal no longer matches
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE dispatch_line SET packages = 2"))
    assert client.get(f"/trips/{trip['id']}/challans", headers=h).json()[0]["sealed"] is False


def test_challans_are_private_to_each_company(client, admin):
    h = bearer(admin)
    clerk = add_staff(client, admin, "clerk@shree.example", "clerk")
    trip = _trip(client, h, ["Raipur"], (_lr(client, h, packages=1, to_city="Raipur"), 1))
    challan = _add(client, clerk, trip, "Ahmedabad", (_lr(client, h, packages=1, to_city="Raipur"), 1), before="Raipur").json()
    other = register(client, "Other Transport", "o@o.example")
    assert client.get("/challans/open", headers=bearer(other)).json() == []
    assert client.get(f"/trips/{trip['id']}/challans", headers=bearer(other)).status_code == 404
    assert client.post(f"/challans/{challan['id']}/approve", headers=bearer(other)).status_code == 404
    assert _add(client, other, trip, "Ahmedabad", (_lr(client, bearer(other), packages=1, to_city="Raipur"), 1), before="Raipur").status_code == 404

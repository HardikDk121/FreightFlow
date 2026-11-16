from tests.conftest import add_staff, bearer

TRUCK = {"vehicle_number": "gj-03 ab 1234", "inner_length_cm": 500, "inner_width_cm": 200, "inner_height_cm": 200, "payload_kg": 3000, "model_year": 2022, "insurance_expiry": "2099-01-01", "fitness_expiry": "2099-01-01"}
CARTON = {"name": "Carton A", "length_cm": 60, "width_cm": 40, "height_cm": 40, "unit_weight_kg": 18}


def test_party_lifecycle(client, admin):
    h = bearer(admin)
    created = client.post("/parties", json={"name": " Surat Textiles ", "latitude": 21.17, "longitude": 72.83}, headers=h)
    assert created.status_code == 201 and created.json()["name"] == "Surat Textiles"
    party_id = created.json()["id"]
    assert client.post("/parties", json={"name": "surat textiles"}, headers=h).status_code == 409
    assert client.post("/parties", json={"name": "X", "latitude": 21.0}, headers=h).status_code == 422
    assert client.patch(f"/parties/{party_id}", json={"longitude": None}, headers=h).status_code == 422
    assert [p["name"] for p in client.get("/parties?q=TEXT", headers=h).json()] == ["Surat Textiles"]
    assert client.get("/parties?q=100%25", headers=h).json() == []
    assert client.patch(f"/parties/{party_id}", json={"is_active": False}, headers=h).status_code == 200
    assert client.get("/parties", headers=h).json() == []
    assert len(client.get("/parties?include_inactive=true", headers=h).json()) == 1
    assert client.get(f"/parties/{party_id}", headers=h).json()["is_active"] is False


def test_item_type_and_truck_validation(client, admin):
    h = bearer(admin)
    item = client.post("/item-types", json=CARTON, headers=h)
    assert item.status_code == 201 and item.json()["stackable"] is True
    assert client.post("/item-types", json={**CARTON, "name": "Bad", "height_cm": 0}, headers=h).status_code == 422
    assert client.patch(f"/item-types/{item.json()['id']}", json={"length_cm": None}, headers=h).status_code == 422
    resized = client.patch(f"/item-types/{item.json()['id']}", json={"length_cm": 61.5, "stackable": False}, headers=h)
    assert resized.json()["length_cm"] == 61.5 and resized.json()["stackable"] is False

    truck = client.post("/trucks", json=TRUCK, headers=h)
    assert truck.status_code == 201 and truck.json()["vehicle_number"] == "GJ03AB1234"
    assert client.post("/trucks", json={**TRUCK, "vehicle_number": "GJ03AB1234"}, headers=h).status_code == 409
    assert client.post("/trucks", json={**TRUCK, "vehicle_number": "22bh 1234 aa"}, headers=h).json()["vehicle_number"] == "22BH1234AA"
    bad_trucks = (
        {"vehicle_number": "!!"},
        {"vehicle_number": "TRUCK1"},
        {"vehicle_number": "GJ03CW062"},
        {"inner_length_cm": 5},  # metres typed as centimetres
        {"inner_width_cm": 2000},
        {"inner_height_cm": 0},
        {"payload_kg": 3},  # tonnes typed as kilograms
        {"payload_kg": 900000},
        {"label": "x" * 41},
    )
    for bad in bad_trucks:
        assert client.post("/trucks", json={**TRUCK, "vehicle_number": "GJ01AA0001", **bad}, headers=h).status_code == 422, bad
    assert client.patch(f"/trucks/{truck.json()['id']}", json={"payload_kg": 1}, headers=h).status_code == 422
    assert client.post("/item-types", json={**CARTON, "name": "Feather", "unit_weight_kg": 0}, headers=h).status_code == 422


def test_roles_on_master_data(client, admin):
    clerk = add_staff(client, admin, "clerk@shree.example", "clerk")
    manager = add_staff(client, admin, "manager@shree.example", "manager")
    assert client.post("/trucks", json=TRUCK, headers=bearer(clerk)).status_code == 403
    created = client.post("/trucks", json=TRUCK, headers=bearer(manager))
    assert created.status_code == 201
    assert client.patch(f"/trucks/{created.json()['id']}", json={"label": "x"}, headers=bearer(clerk)).status_code == 403
    assert len(client.get("/trucks", headers=bearer(clerk)).json()) == 1

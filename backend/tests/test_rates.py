from decimal import Decimal as D

import pytest

from app.rates.engine import PricingError, Rule, quote
from tests.conftest import add_staff, bearer
from tests.test_lr import NEW_LR

BEARINGS = Rule("per_kg", D("4.50"))
HALKA = Rule("per_package_slab", None, ((D(40), D(400)), (D(35), D(350))))
ROLLS = Rule("per_unit", D(120))


def test_chargeable_weight_is_packages_times_weight_per_package():
    """The bug this replaces charged for one package: 10 packages of 100 kg is 1000 kg, not 100."""
    q = quote(BEARINGS, D(0), packages=10, weight_per_package=D(100), total_weight=None)
    assert (q.chargeable_weight, q.freight, q.rate_per_kg) == (D(1000), D("4500.00"), D("4.50"))
    assert "10 packages × 100 kg = 1000 kg" in q.explanation[0]


def test_a_given_total_overrides_the_multiplication():
    q = quote(BEARINGS, D(0), packages=10, weight_per_package=D(100), total_weight=D(1040))
    assert (q.chargeable_weight, q.freight) == (D(1040), D("4680.00"))


def test_outstation_adds_its_surcharge_per_kg():
    q = quote(BEARINGS, D("1.00"), packages=10, weight_per_package=D(100), total_weight=None)
    assert (q.rate_per_kg, q.freight) == (D("5.50"), D("5500.00"))


def test_halka_maal_is_priced_by_the_size_of_one_package():
    assert quote(HALKA, D(0), 6, D(35), None).freight == D("2100.00")
    assert quote(HALKA, D(0), 6, D(36), None).freight == D("2400.00")  # over 35 kg falls in the 40 kg slab
    assert quote(HALKA, D(0), 6, D(40), None).freight == D("2400.00")
    # an outstation adds Rs 1 for each kg carried: 6 x 35 kg = 210 kg
    assert quote(HALKA, D(1), 6, D(35), None).freight == D("2310.00")
    with pytest.raises(PricingError, match="No slab covers a 41 kg package"):
        quote(HALKA, D(0), 6, D(41), None)
    with pytest.raises(PricingError, match="weight per package"):
        quote(HALKA, D(0), 6, None, D(210))


def test_rolls_and_sheets_are_priced_per_piece():
    assert quote(ROLLS, D(0), 8, None, None).freight == D("960.00")
    assert quote(ROLLS, D(1), 8, D(25), None).freight == D("1160.00")
    with pytest.raises(PricingError, match="surcharge per kg"):
        quote(ROLLS, D(1), 8, None, None)
    with pytest.raises(PricingError, match="weight"):
        quote(BEARINGS, D(0), 8, None, None)


def _matrix(client, h):
    for name, surcharge in (("Raipur", 0), ("Jagdalpur", 1), ("Dhamtari", 1), ("Ambikapur", 1)):
        assert client.post("/stations", json={"name": name, "zone": "Raipur", "surcharge_per_kg": surcharge}, headers=h).status_code == 201
    rules = (
        {"goods_class": "Bearings", "zone": "Raipur", "method": "per_kg", "rate": 4.5},
        {"goods_class": "Halka maal", "zone": "Raipur", "method": "per_package_slab",
         "slabs": [{"up_to_kg": 35, "amount": 350}, {"up_to_kg": 40, "amount": 400}]},
        {"goods_class": "Rolls and sheets", "zone": "Raipur", "method": "per_unit", "rate": 120},
    )
    return [client.post("/rate-rules", json=rule, headers=h).json() for rule in rules]


def test_quote_uses_the_destination_station_and_its_zone(client, admin):
    h = bearer(admin)
    bearings = _matrix(client, h)[0]
    assert client.get("/rates/classes", headers=h).json() == ["Bearings", "Halka maal", "Rolls and sheets"]

    ask = lambda **body: client.post("/rates/quote", json={"goods_class": "bearings", "packages": 10, "weight_per_package": "100", **body}, headers=h)
    raipur, jagdalpur = ask(to_city="raipur").json(), ask(to_city="Jagdalpur").json()
    assert (raipur["freight"], raipur["rate_per_kg"], raipur["rate_rule_id"]) == ("4500.00", "4.50", bearings["id"])
    assert (jagdalpur["freight"], jagdalpur["rate_per_kg"]) == ("5500.00", "5.50")
    assert jagdalpur["explanation"][0] == "Bearings to JAGDALPUR (RAIPUR zone)"
    assert ask(to_city="Mumbai").json()["error"]["code"] == "no_station"
    assert client.post("/rates/quote", json={"goods_class": "Cement", "to_city": "Raipur", "packages": 1}, headers=h).json()["error"]["code"] == "no_rate"
    halka = client.post("/rates/quote", json={"goods_class": "Halka maal", "to_city": "Raipur", "packages": 2, "weight_per_package": "55"}, headers=h)
    assert halka.status_code == 422 and "No slab covers" in halka.json()["error"]["message"]


def test_rate_matrix_rules_and_roles(client, admin):
    h = bearer(admin)
    _matrix(client, h)
    bad_rules = (
        {"goods_class": "X", "zone": "Raipur", "method": "per_kg"},  # no rate
        {"goods_class": "X", "zone": "Raipur", "method": "per_kg", "rate": 0},
        {"goods_class": "X", "zone": "Raipur", "method": "per_package_slab", "rate": 5},  # slabs missing
        {"goods_class": "X", "zone": "Raipur", "method": "per_package_slab", "slabs": [{"up_to_kg": 5, "amount": 1}, {"up_to_kg": 5, "amount": 2}]},
        {"goods_class": "X", "zone": "Raipur", "method": "per_unit", "rate": 5, "slabs": [{"up_to_kg": 5, "amount": 1}]},
    )
    for bad in bad_rules:
        assert client.post("/rate-rules", json=bad, headers=h).status_code == 422, bad
    assert client.post("/rate-rules", json={"goods_class": "BEARINGS", "zone": "raipur", "method": "per_kg", "rate": 9}, headers=h).status_code == 409
    assert client.post("/stations", json={"name": "raipur", "zone": "Raipur"}, headers=h).status_code == 409
    assert client.post("/routes", json={"name": "South", "stops": ["Raipur", "raipur"]}, headers=h).status_code == 422
    route = client.post("/routes", json={"name": "Bastar run", "stops": ["Raipur", "Dhamtari", "Jagdalpur"]}, headers=h)
    assert route.status_code == 201 and route.json()["stops"] == ["RAIPUR", "DHAMTARI", "JAGDALPUR"]
    clerk = add_staff(client, admin, "clerk@shree.example", "clerk")
    assert client.post("/stations", json={"name": "Korba", "zone": "Raipur"}, headers=bearer(clerk)).status_code == 403
    assert len(client.get("/stations", headers=bearer(clerk)).json()) == 4


def test_lr_keeps_its_weight_per_package_and_rate(client, admin):
    h = bearer(admin)
    bearings = _matrix(client, h)[0]
    lr = client.post(
        "/lrs",
        json={**NEW_LR, "packages": 10, "weight_per_package": "100", "weight": "1000", "rate": "4.5", "freight": "4500",
              "rate_rule_id": bearings["id"]},
        headers=h,
    ).json()
    assert (lr["weight_per_package"], lr["weight"], lr["freight"], lr["rate_rule_id"]) == ("100.00", "1000.00", "4500.00", bearings["id"])
    assert client.post("/lrs", json={**NEW_LR, "rate_rule_id": "00000000-0000-0000-0000-000000000000"}, headers=h).status_code == 404

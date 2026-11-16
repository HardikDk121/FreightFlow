from decimal import Decimal as D

from app.eway.rules import Category, Consignment, Leg, Party, evaluate, validity_days

GUJARAT, MAHARASHTRA, CHHATTISGARH = "24", "27", "22"


def _c(value, frm=GUJARAT, to=CHHATTISGARH, category=Category.REGULAR, consignor=True, consignee=True, km=900, leg=Leg.DIRECT):
    return Consignment(D(value) if value is not None else None, frm, to, category, consignor, consignee, km, leg)


def test_inter_state_limit_is_fifty_thousand_exclusive():
    assert evaluate(_c(50_000)).required is False
    over = evaluate(_c(50_001))
    assert over.required is True and over.rule == "Rule 138(1)" and "Rs 50,000" in over.reason


def test_intra_state_limit_follows_the_state():
    assert evaluate(_c(60_000, to=GUJARAT)).required is True
    assert evaluate(_c(60_000, frm=MAHARASHTRA, to=MAHARASHTRA)).required is False
    in_maharashtra = evaluate(_c(100_001, frm=MAHARASHTRA, to=MAHARASHTRA))
    assert in_maharashtra.required is True and "Rs 1,00,000" in in_maharashtra.reason
    # leaving the state, its higher limit no longer applies
    assert evaluate(_c(60_000, frm=MAHARASHTRA, to=GUJARAT)).required is True
    assert any("Gujarat" in note for note in evaluate(_c(10, to=GUJARAT)).notes)


def test_job_work_and_handicraft_need_a_bill_at_any_value_only_across_states():
    for category in (Category.JOB_WORK, Category.HANDICRAFT):
        assert evaluate(_c(100, category=category)).required is True
        assert evaluate(_c(100, to=GUJARAT, category=category)).required is False


def test_household_effects_and_exempt_goods_never_need_one():
    household = evaluate(_c(900_000, category=Category.HOUSEHOLD_EFFECTS))
    assert household.required is False and household.rule == "Rule 138(14)"
    assert any("declaration" in note for note in household.notes)
    assert evaluate(_c(900_000, category=Category.EXEMPT_GOODS)).required is False


def test_missing_value_is_undecided_not_assumed():
    undecided = evaluate(_c(None))
    assert undecided.required is None and "Enter the goods value" in undecided.reason


def test_who_generates_it():
    assert evaluate(_c(80_000)).responsible == Party.CONSIGNOR
    assert evaluate(_c(80_000, consignor=False)).responsible == Party.CONSIGNEE
    neither = evaluate(_c(80_000, consignor=False, consignee=False))
    assert neither.responsible == Party.TRANSPORTER and any("ENR-03" in note for note in neither.notes)
    assert evaluate(_c(10)).responsible is None


def test_part_b_is_skipped_only_on_a_short_leg_within_the_state():
    short = evaluate(_c(80_000, to=GUJARAT, km=40, leg=Leg.CONSIGNOR_TO_HUB))
    assert short.required is True and short.part_b_required is False
    assert evaluate(_c(80_000, to=GUJARAT, km=40, leg=Leg.HUB_TO_CONSIGNEE)).part_b_required is False
    assert evaluate(_c(80_000, to=GUJARAT, km=40)).part_b_required is True  # direct delivery
    assert evaluate(_c(80_000, to=GUJARAT, km=50, leg=Leg.CONSIGNOR_TO_HUB)).part_b_required is True
    assert evaluate(_c(80_000, km=40, leg=Leg.CONSIGNOR_TO_HUB)).part_b_required is True  # inter-state


def test_validity_is_a_day_per_200_km_or_part():
    assert [validity_days(km) for km in (1, 200, 201, 400, 900)] == [1, 1, 2, 2, 5]
    assert evaluate(_c(80_000, km=900)).validity_days == 5
    assert evaluate(_c(80_000, km=None)).validity_days is None

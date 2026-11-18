import uuid
from decimal import Decimal as D

from app.planner.planner import Load, TruckSpec, plan_load

TRUCK = TruckSpec(D(500), D(200), D(200), D(3000))


def _load(pending, dims, weight):
    return Load(uuid.uuid4(), pending, tuple(D(x) for x in dims) if dims else None, D(weight) if weight else None)


def test_worked_example_from_the_proposal():
    """Appendix C: three LRs load in full, 12 of the fourth's 30 cartons fill what is left."""
    loads = [
        _load(40, (60, 40, 40), 18),
        _load(24, (100, 50, 50), 30),
        _load(50, (50, 50, 40), 20),
        _load(30, (60, 60, 50), 20),
    ]
    plan = plan_load(TRUCK, loads)
    assert [line.packages for line in plan.lines] == [40, 24, 50, 12]
    assert plan.usable_volume_m3 == D(17)
    assert plan.volume_used_m3 == D(17)
    assert plan.weight_used_kg == D(2680)


def test_payload_limits_before_space():
    plan = plan_load(TRUCK, [_load(100, (30, 30, 30), 50)])
    assert plan.lines[0].packages == 60 and plan.weight_used_kg == D(3000)


def test_a_later_small_lr_fills_space_an_earlier_big_one_left():
    big, small = _load(1, (490, 190, 190), 100), _load(500, (20, 20, 20), 1)
    plan = plan_load(TRUCK, [_load(1, (490, 190, 150), 100), big, small])
    assert [line.lr_id for line in plan.lines] == [plan.lines[0].lr_id, small.lr_id]


def test_unsized_and_oversized_are_reported_not_planned():
    unsized, long_pipe = _load(5, None, None), _load(2, (600, 10, 10), 5)
    plan = plan_load(TRUCK, [unsized, long_pipe])
    assert plan.lines == [] and plan.unsized == [unsized.lr_id] and plan.too_big == [long_pipe.lr_id]


def test_a_load_with_weight_but_no_size_is_fitted_by_weight_alone():
    heavy = _load(100, None, 50)
    plan = plan_load(TRUCK, [heavy])
    assert plan.lines[0].packages == 60 and plan.weight_only == [heavy.lr_id]
    assert plan.volume_used_m3 == 0 and plan.weight_used_kg == D(3000)

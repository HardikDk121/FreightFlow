"""Load planning by weight and volume. Pure functions: no database, no clock, same input gives same plan.

Version 1 checks capacity; it does not place boxes in 3D. The usable share stands in for the
space lost between boxes and must be calibrated against real loads.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal

USABLE_VOLUME_SHARE = Decimal("0.85")
_CM3_PER_M3 = Decimal(1_000_000)


@dataclass(frozen=True)
class TruckSpec:
    length_cm: Decimal
    width_cm: Decimal
    height_cm: Decimal
    payload_kg: Decimal


@dataclass(frozen=True)
class Load:
    """One pending LR, oldest first. Size is None when the LR has no package type; weight is None
    only for an old LR saved without one."""

    lr_id: uuid.UUID
    pending: int
    unit_dims_cm: tuple[Decimal, Decimal, Decimal] | None
    unit_weight_kg: Decimal | None


@dataclass(frozen=True)
class PlannedLine:
    lr_id: uuid.UUID
    packages: int
    volume_m3: Decimal
    weight_kg: Decimal


@dataclass(frozen=True)
class Plan:
    lines: list[PlannedLine]
    weight_only: list[uuid.UUID]  # no package type: planned by weight, their space is not counted
    unsized: list[uuid.UUID]  # neither size nor weight: the planner cannot judge these
    too_big: list[uuid.UUID]  # one package does not fit through the truck in any orientation
    usable_volume_m3: Decimal
    volume_used_m3: Decimal
    weight_used_kg: Decimal


def _fits(unit: tuple[Decimal, Decimal, Decimal], truck: TruckSpec) -> bool:
    return all(u <= t for u, t in zip(sorted(unit), sorted((truck.length_cm, truck.width_cm, truck.height_cm))))


def plan_load(truck: TruckSpec, loads: list[Load]) -> Plan:
    """Fill oldest first. Load as many packages of each LR as space and payload allow, then
    try the next LR with what is left, so a truck is not sent half empty behind one big LR."""
    usable = truck.length_cm * truck.width_cm * truck.height_cm * USABLE_VOLUME_SHARE
    volume_left, weight_left = usable, truck.payload_kg
    lines: list[PlannedLine] = []
    weight_only: list[uuid.UUID] = []
    unsized: list[uuid.UUID] = []
    too_big: list[uuid.UUID] = []
    for load in loads:
        if load.unit_weight_kg is None:
            unsized.append(load.lr_id)
            continue
        if load.unit_dims_cm is None:
            unit_volume = Decimal(0)
            count = min(load.pending, int(weight_left // load.unit_weight_kg))
        elif not _fits(load.unit_dims_cm, truck):
            too_big.append(load.lr_id)
            continue
        else:
            unit_volume = load.unit_dims_cm[0] * load.unit_dims_cm[1] * load.unit_dims_cm[2]
            count = min(load.pending, int(volume_left // unit_volume), int(weight_left // load.unit_weight_kg))
        if count <= 0:
            continue
        if load.unit_dims_cm is None:
            weight_only.append(load.lr_id)
        volume_left -= unit_volume * count
        weight_left -= load.unit_weight_kg * count
        lines.append(PlannedLine(load.lr_id, count, unit_volume * count / _CM3_PER_M3, load.unit_weight_kg * count))
    return Plan(
        lines=lines,
        weight_only=weight_only,
        unsized=unsized,
        too_big=too_big,
        usable_volume_m3=usable / _CM3_PER_M3,
        volume_used_m3=(usable - volume_left) / _CM3_PER_M3,
        weight_used_kg=truck.payload_kg - weight_left,
    )


@dataclass(frozen=True)
class Cargo:
    """Goods on a multi-stop trip. `pickup` and `drop` are positions in the trip's list of stops;
    goods loaded at the origin have pickup -1."""

    pickup: int
    drop: int
    weight_kg: Decimal
    volume_cm3: Decimal  # 0 when the LR has no package type, so only its weight is checked


@dataclass(frozen=True)
class Overload:
    leg: int  # position of the stop this leg leads to
    what: str  # "weight" or "space"
    load: Decimal
    limit: Decimal


def first_overload(truck: TruckSpec, stop_count: int, cargo: list[Cargo], from_leg: int) -> Overload | None:
    """The first leg, from `from_leg` on, where the goods on board exceed the truck. A truck that
    leaves 70% full can take more on the road only if no later leg is pushed over, so every leg
    is checked, not one total. Goods are on board from the leg after their pickup to the leg
    that reaches their drop."""
    usable = truck.length_cm * truck.width_cm * truck.height_cm * USABLE_VOLUME_SHARE
    for leg in range(max(from_leg, 0), stop_count):
        on_board = [c for c in cargo if c.pickup < leg <= c.drop]
        weight = sum((c.weight_kg for c in on_board), Decimal(0))
        if weight > truck.payload_kg:
            return Overload(leg, "weight", weight, truck.payload_kg)
        volume = sum((c.volume_cm3 for c in on_board), Decimal(0))
        if volume > usable:
            return Overload(leg, "space", volume / _CM3_PER_M3, usable / _CM3_PER_M3)
    return None

"""Cargo added to a truck that is already on the road.

An issued challan is never edited. More cargo is a new supplementary challan on the same trip:
requested by whoever is loading, approved by the person who dispatched the trip, and issued when
the driver signs for what was counted on. Dispatch lines are written only at that last step, so
a request that is never approved or signed changes nothing about what is recorded as carried.
"""

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.clock import midnight_after, today
from app.dispatch.addition_schemas import AdditionRequest, ChallanLine, ChallanRead, DriverSignOff
from app.dispatch.service import _locked_trip, _spec, is_sealed, seal, stop_branches
from app.errors import AppError, conflict, forbidden, not_found
from app.eway.rules import validity_days
from app.models import Challan, DispatchLine, ItemType, Lr, Trip, Truck, User
from app.permissions import P, has
from app.planner.planner import Cargo, first_overload
from app.security import utcnow

_OPEN = ("requested", "awaiting_driver")


def _cargo(lr: Lr, item: ItemType | None, packages: int, pickup: int, drop: int) -> Cargo:
    if item is not None:
        weight = Decimal(str(item.unit_weight_kg)) * packages
        volume = Decimal(str(item.length_cm)) * Decimal(str(item.width_cm)) * Decimal(str(item.height_cm)) * packages
    else:
        # No package type: spread the LR's own weight over its packages; its space is unknown.
        weight = (lr.weight or Decimal(0)) / lr.packages * packages
        volume = Decimal(0)
    return Cargo(pickup=pickup, drop=drop, weight_kg=weight, volume_cm3=volume)


def _check(
    session: Session,
    trip: Trip,
    loaded_at: str,
    insert_before: str | None,
    wanted: dict[uuid.UUID, int],
    *,
    lock: bool = True,
):
    """Everything that must hold for these packages to join this trip at this place.
    Returns the route with the loading stop in it, the LRs, and warnings for the approver.
    Runs at request, again at approval, and again at sign-off, because the trip keeps moving.
    `lock=False` is for showing a request without holding its LRs."""
    if trip.status != "dispatched":
        raise conflict("This trip is finished, so nothing more can be loaded on it.")
    route = list(trip.route)
    on_board = session.execute(
        select(DispatchLine, Lr, ItemType, Challan)
        .join(Lr, Lr.id == DispatchLine.lr_id)
        .join(Challan, Challan.id == DispatchLine.challan_id)
        .outerjoin(ItemType, ItemType.id == Lr.item_type_id)
        .where(DispatchLine.trip_id == trip.id)
    ).all()
    # The truck has reached at least the furthest stop where something was delivered.
    reached = max((route.index(lr.to_city.upper()) for line, lr, _, _ in on_board if line.delivered_at), default=-1)

    if loaded_at in route:
        if insert_before is not None:
            raise AppError(422, "already_a_stop", f"{loaded_at} is already a stop on this trip.")
        load_at = route.index(loaded_at)
        if load_at < reached:
            raise conflict(f"The truck has already passed {loaded_at}.")
    else:
        if insert_before is None or insert_before not in route:
            raise AppError(
                422, "stop_needed", f"{loaded_at} is not a stop on this trip. Say which stop it comes before."
            )
        load_at = route.index(insert_before)
        if load_at <= reached:
            raise conflict(f"The truck has already reached {route[reached]}, so it cannot stop before {insert_before}.")
        route.insert(load_at, loaded_at)

    query = select(Lr).where(Lr.id.in_(wanted)).order_by(Lr.id)
    lrs = session.scalars(query.with_for_update() if lock else query).all()
    if len(lrs) != len(wanted):
        raise not_found("LR")
    sent = dict(
        session.execute(
            select(DispatchLine.lr_id, func.sum(DispatchLine.packages))
            .where(DispatchLine.lr_id.in_(wanted))
            .group_by(DispatchLine.lr_id)
        ).all()
    )
    items = {i.id: i for i in session.scalars(select(ItemType).where(ItemType.id.in_([lr.item_type_id for lr in lrs if lr.item_type_id])))}
    added = []
    for lr in lrs:
        city = lr.to_city.upper()
        if lr.status != "confirmed":
            raise conflict(f"LR {lr.lr_number} is cancelled.")
        if city not in route or route.index(city) <= load_at:
            raise conflict(f"LR {lr.lr_number} is for {city}, which is not a stop after {loaded_at} on this trip.")
        remaining = lr.packages - sent.get(lr.id, 0)
        if wanted[lr.id] > remaining:
            raise conflict(f"LR {lr.lr_number} has only {remaining} packages pending.")
        if lr.ewb_status == "pending":
            raise conflict(f"LR {lr.lr_number} needs an e-way bill before it can move. Add the number on the LR first.")
        added.append(_cargo(lr, items.get(lr.item_type_id), wanted[lr.id], load_at, route.index(city)))

    # Goods already on the truck, placed on the (possibly longer) route.
    carried = [
        _cargo(lr, item, line.packages, -1 if challan.seq == 0 else route.index(challan.loaded_at), route.index(lr.to_city.upper()))
        for line, lr, item, challan in on_board
        if line.delivered_at is None
    ]
    truck = session.get_one(Truck, trip.truck_id)
    over = first_overload(_spec(truck), len(route), carried + added, from_leg=load_at + 1)
    if over is not None:
        unit = "kg" if over.what == "weight" else "m³"
        raise conflict(
            f"Too much {over.what} for truck {truck.vehicle_number} on the way to {route[over.leg]}: "
            f"{over.load:.0f} {unit} against a limit of {over.limit:.0f} {unit}."
        )

    # Goods loaded on the road sit nearest the door. If they travel further than goods already
    # behind them, they are in the way when those are unloaded.
    warnings = []
    for position in range(load_at + 1, len(route)):
        behind = sum(line.packages for line, lr, _, _ in on_board if line.delivered_at is None and route.index(lr.to_city.upper()) == position)
        in_front = sum(wanted[lr.id] for lr in lrs if route.index(lr.to_city.upper()) > position)
        if behind and in_front:
            warnings.append(
                f"{in_front} of these packages go beyond {route[position]} and will be in front of "
                f"{behind} packages that unload there."
            )
    return route, lrs, warnings


def _wanted(challan: Challan) -> dict[uuid.UUID, int]:
    return {uuid.UUID(line["lr_id"]): line["packages"] for line in challan.requested_lines}


def _approver_of(trip: Trip, challan: Challan, user: User) -> bool:
    """The person who dispatched the trip approves. If they made the request themselves, an admin does."""
    if user.id == challan.requested_by:
        return False
    if user.id == trip.dispatched_by:
        return True
    return has(user, P.APPROVALS_DECIDE) and challan.requested_by == trip.dispatched_by


def _read(session: Session, challan: Challan, user: User, warnings: list[str] | None = None) -> ChallanRead:
    trip = session.get_one(Trip, challan.trip_id)
    if warnings is None and challan.status == "requested":
        # Show the approver what they would be agreeing to, or why it can no longer go ahead.
        try:
            warnings = _check(session, trip, challan.loaded_at, challan.insert_before, _wanted(challan), lock=False)[2]
        except AppError as problem:
            warnings = [f"This cannot be approved as it stands: {problem.message}"]
    loaded = dict(
        session.execute(select(DispatchLine.lr_id, DispatchLine.packages).where(DispatchLine.challan_id == challan.id)).all()
    )
    wanted = _wanted(challan)
    lrs = {lr.id: lr for lr in session.scalars(select(Lr).where(Lr.id.in_(set(wanted) | set(loaded))))}
    names = dict(
        session.execute(
            select(User.id, User.name).where(User.id.in_([u for u in (challan.requested_by, challan.approved_by) if u]))
        ).all()
    )
    return ChallanRead(
        id=challan.id,
        trip_id=trip.id,
        vehicle_number=session.get_one(Truck, trip.truck_id).vehicle_number,
        challan_number=challan.challan_number,
        seq=challan.seq,
        status=challan.status,
        loaded_at=challan.loaded_at,
        requested_by=names[challan.requested_by],
        approved_by=names.get(challan.approved_by),
        created_at=challan.created_at,
        issued_at=challan.issued_at,
        driver_name=challan.driver_name,
        shortage_note=challan.shortage_note,
        void_reason=challan.void_reason,
        lines=[
            ChallanLine(
                lr_id=lr_id,
                lr_number=lrs[lr_id].lr_number,
                consignee_name=lrs[lr_id].consignee_name,
                to_city=lrs[lr_id].to_city.upper(),
                requested=wanted.get(lr_id, loaded.get(lr_id, 0)),
                loaded=loaded.get(lr_id, 0) if challan.status == "issued" else None,
            )
            for lr_id in sorted(lrs, key=lambda i: lrs[i].lr_number)
        ],
        warnings=warnings or [],
        sealed=is_sealed(session, challan) if challan.status == "issued" else None,
        can_approve=challan.status == "requested" and _approver_of(trip, challan, user),
        can_sign=challan.status == "awaiting_driver",
        can_void=challan.status in _OPEN
        and (user.id in (challan.requested_by, trip.dispatched_by) or has(user, P.APPROVALS_DECIDE)),
    )


def _challan(session: Session, challan_id: uuid.UUID) -> tuple[Challan, Trip]:
    """The challan with its trip locked, so approval, sign-off and delivery take turns."""
    challan = session.get(Challan, challan_id)
    if challan is None:
        raise not_found("Challan")
    return challan, _locked_trip(session, challan.trip_id)


def request(session: Session, actor: User, trip_id: uuid.UUID, data: AdditionRequest) -> ChallanRead:
    trip = _locked_trip(session, trip_id)
    wanted = {line.lr_id: line.packages for line in data.lines}
    _, _, warnings = _check(session, trip, data.loaded_at, data.insert_before, wanted)
    # Numbers run S1, S2, S3 with no gaps: a voided request keeps its number.
    seq = session.scalar(select(func.max(Challan.seq)).where(Challan.trip_id == trip.id)) + 1
    challan = Challan(
        company_id=actor.company_id,
        trip_id=trip.id,
        seq=seq,
        challan_number=f"CH-{trip.trip_no}/S{seq}",
        loaded_at=data.loaded_at,
        insert_before=data.insert_before,
        status="requested",
        requested_lines=[{"lr_id": str(lr_id), "packages": packages} for lr_id, packages in wanted.items()],
        requested_by=actor.id,
    )
    session.add(challan)
    session.flush()
    session.refresh(challan)
    audit.record(
        session,
        company_id=actor.company_id,
        actor_id=actor.id,
        action="challan.request",
        entity="challan",
        entity_id=challan.id,
        detail={"challan_number": challan.challan_number, "loaded_at": data.loaded_at},
    )
    return _read(session, challan, actor, warnings)


def approve(session: Session, actor: User, challan_id: uuid.UUID) -> ChallanRead:
    challan, trip = _challan(session, challan_id)
    if challan.status != "requested":
        raise conflict("This request is no longer waiting for approval.")
    if not _approver_of(trip, challan, actor):
        raise forbidden()
    route, _, warnings = _check(session, trip, challan.loaded_at, challan.insert_before, _wanted(challan))
    stop_added = route != list(trip.route)
    trip.route = route
    trip.stop_branch_ids = sorted(set(trip.stop_branch_ids) | set(stop_branches(session, route, [])))
    challan.status = "awaiting_driver"
    challan.approved_by = actor.id
    challan.approved_at = utcnow()
    session.flush()
    audit.record(
        session,
        company_id=actor.company_id,
        actor_id=actor.id,
        action="challan.approve",
        entity="challan",
        entity_id=challan.id,
        detail={"challan_number": challan.challan_number, "stop_added": challan.loaded_at if stop_added else None},
    )
    return _read(session, challan, actor, warnings)


def void(session: Session, actor: User, challan_id: uuid.UUID, reason: str) -> ChallanRead:
    """Withdraw or refuse an addition before the driver has signed. An issued challan cannot be voided:
    by then the goods are on the truck."""
    challan, trip = _challan(session, challan_id)
    if challan.status not in _OPEN:
        raise conflict("Only an addition the driver has not signed for can be voided.")
    if actor.id not in (challan.requested_by, trip.dispatched_by) and not has(actor, P.APPROVALS_DECIDE):
        raise forbidden()
    challan.status = "void"
    challan.voided_by = actor.id
    challan.voided_at = utcnow()
    challan.void_reason = reason
    session.flush()
    audit.record(
        session,
        company_id=actor.company_id,
        actor_id=actor.id,
        action="challan.void",
        entity="challan",
        entity_id=challan.id,
        detail={"challan_number": challan.challan_number, "reason": reason},
    )
    return _read(session, challan, actor)


def sign(session: Session, actor: User, challan_id: uuid.UUID, data: DriverSignOff) -> ChallanRead:
    """The driver signs for what was counted onto the truck. Only now are the lines written, the
    challan sealed, and the driver answerable for the goods."""
    challan, trip = _challan(session, challan_id)
    if challan.status != "awaiting_driver":
        raise conflict("This challan is not waiting for the driver.")
    requested = _wanted(challan)
    counted = {count.lr_id: count.packages for count in data.counts}
    if set(counted) - set(requested):
        raise AppError(422, "unknown_lr", "A count was given for an LR that is not on this challan.")
    loaded = {lr_id: counted.get(lr_id, packages) for lr_id, packages in requested.items()}
    if any(loaded[lr_id] > requested[lr_id] for lr_id in loaded):
        raise conflict("The driver cannot sign for more packages than were approved. Request the extra separately.")
    loaded = {lr_id: packages for lr_id, packages in loaded.items() if packages > 0}
    if not loaded:
        raise conflict("Nothing was loaded. Void this challan instead.")

    _, lrs, _ = _check(session, trip, challan.loaded_at, None, loaded)
    truck = session.get_one(Truck, trip.truck_id)
    session.add_all(
        DispatchLine(company_id=actor.company_id, trip_id=trip.id, challan_id=challan.id, lr_id=lr_id, packages=packages)
        for lr_id, packages in loaded.items()
    )
    # Putting the goods on this vehicle is Part B of each e-way bill; its validity runs from now.
    for lr in lrs:
        if lr.ewb_status == "awaiting_part_b":
            lr.ewb_status = "active"
            lr.ewb_vehicle_number = truck.vehicle_number
            lr.ewb_valid_until = midnight_after(today() + dt.timedelta(days=validity_days(lr.distance_km) - 1))
    by_id = {lr.id: lr for lr in lrs}
    short = [
        f"{by_id[lr_id].lr_number if lr_id in by_id else 'An LR'}: {loaded.get(lr_id, 0)} of {packages} loaded"
        for lr_id, packages in requested.items()
        if loaded.get(lr_id, 0) < packages
    ]
    challan.status = "issued"
    challan.issued_at = utcnow()
    challan.driver_name = data.driver_name
    challan.driver_signature = [[list(point) for point in stroke] for stroke in data.signature]
    challan.shortage_note = "; ".join(short) or None
    session.flush()
    seal(session, challan)
    audit.record(
        session,
        company_id=actor.company_id,
        actor_id=actor.id,
        action="challan.issue",
        entity="challan",
        entity_id=challan.id,
        detail={"challan_number": challan.challan_number, "driver": data.driver_name, "shortage": challan.shortage_note},
    )
    return _read(session, challan, actor)


def for_trip(session: Session, user: User, trip_id: uuid.UUID) -> list[ChallanRead]:
    if session.get(Trip, trip_id) is None:
        raise not_found("Trip")
    challans = session.scalars(select(Challan).where(Challan.trip_id == trip_id).order_by(Challan.seq))
    return [_read(session, challan, user) for challan in challans]


def open_additions(session: Session, user: User) -> list[ChallanRead]:
    """Additions still waiting for approval or for the driver, the oldest first."""
    challans = session.scalars(select(Challan).where(Challan.status.in_(_OPEN)).order_by(Challan.created_at))
    return [_read(session, challan, user) for challan in challans]

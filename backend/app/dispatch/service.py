import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit
from app.clock import today
from app.dispatch.schemas import (
    DispatchRequest,
    PendingDestination,
    PendingLr,
    PlanLine,
    PlanRead,
    TripLineRead,
    TripRead,
)
from app.errors import conflict, not_found
from app.models import DispatchLine, ItemType, Lr, Trip, Truck, User
from app.planner.planner import Load, TruckSpec, plan_load
from app.security import utcnow


def _dispatched():
    """Packages already sent, per LR. Pending is never stored: it is always packages minus this sum."""
    return (
        select(DispatchLine.lr_id, func.sum(DispatchLine.packages).label("packages"))
        .group_by(DispatchLine.lr_id)
        .subquery()
    )


def _pending_rows(session: Session, *, destination: str | None, older_than_days: int | None):
    """(Lr, pending, ItemType | None) for confirmed LRs with packages still waiting, oldest first."""
    sent = _dispatched()
    pending = Lr.packages - func.coalesce(sent.c.packages, 0)
    query = (
        select(Lr, pending, ItemType)
        .outerjoin(sent, sent.c.lr_id == Lr.id)
        .outerjoin(ItemType, ItemType.id == Lr.item_type_id)
        .where(Lr.status == "confirmed", pending > 0)
        .order_by(Lr.lr_date, Lr.series_no)
    )
    if destination is not None:
        query = query.where(func.lower(Lr.to_city) == destination.strip().lower())
    if older_than_days is not None:
        query = query.where(Lr.lr_date < today() - dt.timedelta(days=older_than_days))
    return session.execute(query).all()


def _pending_lr(lr: Lr, pending: int, item_type: ItemType | None) -> PendingLr:
    return PendingLr(
        lr_id=lr.id,
        lr_number=lr.lr_number,
        lr_date=lr.lr_date,
        days_waiting=(today() - lr.lr_date).days,
        to_city=lr.to_city,
        consignor_name=lr.consignor_name,
        consignee_name=lr.consignee_name,
        goods_description=lr.goods_description,
        packages=lr.packages,
        pending=pending,
        sized=item_type is not None,
    )


def pending_lrs(
    session: Session, *, destination: str | None = None, older_than_days: int | None = None
) -> list[PendingLr]:
    rows = _pending_rows(session, destination=destination, older_than_days=older_than_days)
    return [_pending_lr(lr, pending, item_type) for lr, pending, item_type in rows]


def pending_destinations(session: Session) -> list[PendingDestination]:
    """Waiting goods grouped by destination, the one waiting longest first."""
    groups: dict[str, PendingDestination] = {}
    for row in pending_lrs(session):
        key = row.to_city.upper()
        group = groups.get(key)
        if group is None:
            # Rows arrive oldest first, so the first LR seen for a city is its oldest.
            groups[key] = PendingDestination(
                to_city=key, lr_count=1, packages=row.pending, oldest_lr_date=row.lr_date, days_waiting=row.days_waiting
            )
        else:
            group.lr_count += 1
            group.packages += row.pending
    return list(groups.values())


def _truck(session: Session, truck_id: uuid.UUID) -> Truck:
    truck = session.get(Truck, truck_id)
    if truck is None or not truck.is_active:
        raise not_found("Truck")
    return truck


def _pct(used: Decimal, capacity: Decimal) -> int:
    return round(used * 100 / capacity)


def plan(session: Session, truck_id: uuid.UUID, destination: str) -> PlanRead:
    truck = _truck(session, truck_id)
    rows = _pending_rows(session, destination=destination, older_than_days=None)
    by_id = {lr.id: _pending_lr(lr, pending, item_type) for lr, pending, item_type in rows}
    spec = TruckSpec(
        Decimal(str(truck.inner_length_cm)),
        Decimal(str(truck.inner_width_cm)),
        Decimal(str(truck.inner_height_cm)),
        Decimal(str(truck.payload_kg)),
    )
    loads = [
        Load(
            lr_id=lr.id,
            pending=pending,
            unit_dims_cm=(
                (Decimal(str(item.length_cm)), Decimal(str(item.width_cm)), Decimal(str(item.height_cm)))
                if item
                else None
            ),
            unit_weight_kg=Decimal(str(item.unit_weight_kg)) if item else None,
        )
        for lr, pending, item in rows
    ]
    result = plan_load(spec, loads)
    return PlanRead(
        lines=[
            PlanLine(
                lr_id=line.lr_id,
                lr_number=by_id[line.lr_id].lr_number,
                consignee_name=by_id[line.lr_id].consignee_name,
                pending=by_id[line.lr_id].pending,
                load=line.packages,
                volume_m3=round(line.volume_m3, 2),
                weight_kg=round(line.weight_kg, 2),
            )
            for line in result.lines
        ],
        unsized=[by_id[i] for i in result.unsized],
        too_big=[by_id[i] for i in result.too_big],
        usable_volume_m3=round(result.usable_volume_m3, 2),
        volume_used_m3=round(result.volume_used_m3, 2),
        # Share of the whole truck body, so a full plan reads as the usable share (85%), not 100%.
        volume_used_pct=_pct(result.volume_used_m3, spec.length_cm * spec.width_cm * spec.height_cm / 1_000_000),
        payload_kg=spec.payload_kg,
        weight_used_kg=round(result.weight_used_kg, 2),
        payload_used_pct=_pct(result.weight_used_kg, spec.payload_kg),
    )


def _trip_read(session: Session, trip: Trip) -> TripRead:
    truck = session.get_one(Truck, trip.truck_id)
    rows = session.execute(
        select(DispatchLine, Lr)
        .join(Lr, Lr.id == DispatchLine.lr_id)
        .where(DispatchLine.trip_id == trip.id)
        .order_by(Lr.lr_date, Lr.series_no)
    ).all()
    return TripRead(
        id=trip.id,
        vehicle_number=truck.vehicle_number,
        destination=trip.destination,
        driver_name=trip.driver_name,
        driver_phone=trip.driver_phone,
        status=trip.status,
        dispatched_at=trip.dispatched_at,
        completed_at=trip.completed_at,
        lines=[
            TripLineRead(
                id=line.id,
                lr_id=lr.id,
                lr_number=lr.lr_number,
                consignee_name=lr.consignee_name,
                packages=line.packages,
                delivered_at=line.delivered_at,
            )
            for line, lr in rows
        ],
    )


def dispatch(session: Session, actor: User, data: DispatchRequest) -> TripRead:
    """Send a truck out. Every LR row is locked while its remaining packages are checked, so two
    dispatchers cannot both load the same packages."""
    truck = _truck(session, data.truck_id)
    # Read now: a failed insert below expires every loaded row.
    truck_busy = conflict(f"Truck {truck.vehicle_number} is already out on a trip.")
    if session.scalar(select(Trip.id).where(Trip.truck_id == truck.id, Trip.status == "dispatched")) is not None:
        raise truck_busy
    wanted = {line.lr_id: line.packages for line in data.lines}
    lrs = session.scalars(select(Lr).where(Lr.id.in_(wanted)).order_by(Lr.id).with_for_update()).all()
    if len(lrs) != len(wanted):
        raise not_found("LR")
    sent = dict(
        session.execute(
            select(DispatchLine.lr_id, func.sum(DispatchLine.packages))
            .where(DispatchLine.lr_id.in_(wanted))
            .group_by(DispatchLine.lr_id)
        ).all()
    )
    for lr in lrs:
        if lr.status != "confirmed":
            raise conflict(f"LR {lr.lr_number} is cancelled.")
        remaining = lr.packages - sent.get(lr.id, 0)
        if wanted[lr.id] > remaining:
            raise conflict(f"LR {lr.lr_number} has only {remaining} packages pending.")

    trip = Trip(
        company_id=actor.company_id,
        truck_id=truck.id,
        destination=data.destination.upper(),
        driver_name=data.driver_name,
        driver_phone=data.driver_phone,
        dispatched_by=actor.id,
    )
    session.add(trip)
    try:
        session.flush()
    except IntegrityError as exc:
        # Two dispatchers picked the same truck at the same moment; the unique index let one through.
        raise truck_busy from exc
    session.add_all(
        DispatchLine(company_id=actor.company_id, trip_id=trip.id, lr_id=lr_id, packages=packages)
        for lr_id, packages in wanted.items()
    )
    session.flush()
    session.refresh(trip)
    audit.record(
        session,
        company_id=actor.company_id,
        actor_id=actor.id,
        action="trip.dispatch",
        entity="trip",
        entity_id=trip.id,
        detail={"truck": truck.vehicle_number, "lines": {lr.lr_number: wanted[lr.id] for lr in lrs}},
    )
    return _trip_read(session, trip)


def list_trips(session: Session, *, status: str | None, limit: int, offset: int) -> list[TripRead]:
    query = select(Trip).order_by(Trip.dispatched_at.desc()).limit(limit).offset(offset)
    if status is not None:
        query = query.where(Trip.status == status)
    return [_trip_read(session, trip) for trip in session.scalars(query)]


def get_trip(session: Session, trip_id: uuid.UUID) -> TripRead:
    trip = session.get(Trip, trip_id)
    if trip is None:
        raise not_found("Trip")
    return _trip_read(session, trip)


def deliver(session: Session, actor: User, trip_id: uuid.UUID, line_id: uuid.UUID) -> TripRead:
    """Mark one LR on a trip as delivered. The trip completes when its last line is delivered."""
    trip = session.get(Trip, trip_id, with_for_update=True)
    if trip is None:
        raise not_found("Trip")
    line = session.scalar(select(DispatchLine).where(DispatchLine.id == line_id, DispatchLine.trip_id == trip.id))
    if line is None:
        raise not_found("Trip line")
    if line.delivered_at is not None:
        raise conflict("This delivery is already confirmed.")
    line.delivered_at = utcnow()
    line.delivered_by = actor.id
    session.flush()
    undelivered = session.scalar(
        select(func.count())
        .select_from(DispatchLine)
        .where(DispatchLine.trip_id == trip.id, DispatchLine.delivered_at.is_(None))
    )
    if undelivered == 0:
        trip.status = "completed"
        trip.completed_at = utcnow()
        session.flush()
    audit.record(
        session,
        company_id=actor.company_id,
        actor_id=actor.id,
        action="trip.deliver",
        entity="dispatch_line",
        entity_id=line.id,
        detail={"trip_id": str(trip.id), "trip_completed": undelivered == 0},
    )
    return _trip_read(session, trip)

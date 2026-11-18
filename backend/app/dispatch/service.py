import datetime as dt
import hashlib
import json
import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit
from app.clock import midnight_after, today
from app.dispatch.schemas import (
    DispatchRequest,
    LoadSheetRow,
    PendingDestination,
    PendingLr,
    PlanLine,
    PlanRead,
    Suggestion,
    TripLineRead,
    TripRead,
    TripStop,
)
from app.errors import conflict, not_found
from app.eway.rules import validity_days
from app.lr import service as lr_service
from app.models import Challan, DispatchLine, ItemType, Lr, Route, Trip, Truck, User
from app.planner.planner import Load, Plan, TruckSpec, plan_load
from app.security import utcnow

PendingRow = tuple[Lr, int, ItemType | None]


def _pending_rows(
    session: Session, *, cities: list[str] | None = None, older_than_days: int | None = None
) -> list[PendingRow]:
    """(Lr, pending, ItemType | None) for confirmed LRs with packages still waiting, oldest first.
    Pending is never stored: it is always an LR's packages minus what trips have taken."""
    sent = (
        select(DispatchLine.lr_id, func.sum(DispatchLine.packages).label("packages"))
        .group_by(DispatchLine.lr_id)
        .subquery()
    )
    pending = Lr.packages - func.coalesce(sent.c.packages, 0)
    query = (
        select(Lr, pending, ItemType)
        .outerjoin(sent, sent.c.lr_id == Lr.id)
        .outerjoin(ItemType, ItemType.id == Lr.item_type_id)
        .where(Lr.status == "confirmed", pending > 0)
        .order_by(Lr.lr_date, Lr.series_no)
    )
    if cities is not None:
        query = query.where(func.upper(Lr.to_city).in_([city.upper() for city in cities]))
    if older_than_days is not None:
        query = query.where(Lr.lr_date < today() - dt.timedelta(days=older_than_days))
    return [tuple(row) for row in session.execute(query).all()]


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
        weight_kg=round((lr.weight or Decimal(0)) * pending / lr.packages, 2),
        ewb_status=lr.ewb_status,
        freight_by=lr.freight_by,
        sized=item_type is not None,
    )


def pending_lrs(
    session: Session, *, destination: str | None = None, older_than_days: int | None = None
) -> list[PendingLr]:
    """`destination` may be one city or several separated by commas (the stops of a route)."""
    cities = [city.strip() for city in destination.split(",") if city.strip()] if destination else None
    rows = _pending_rows(session, cities=cities, older_than_days=older_than_days)
    return [_pending_lr(*row) for row in rows]


def pending_destinations(session: Session) -> list[PendingDestination]:
    """Waiting goods grouped by destination, the one waiting longest first."""
    groups: dict[str, PendingDestination] = {}
    for row in pending_lrs(session):
        key = row.to_city.upper()
        group = groups.get(key)
        if group is None:
            # Rows arrive oldest first, so the first LR seen for a city is its oldest.
            groups[key] = PendingDestination(
                to_city=key,
                lr_count=1,
                packages=row.pending,
                weight_kg=row.weight_kg,
                oldest_lr_date=row.lr_date,
                days_waiting=row.days_waiting,
            )
        else:
            group.lr_count += 1
            group.packages += row.pending
            group.weight_kg += row.weight_kg
    return list(groups.values())


def _truck(session: Session, truck_id: uuid.UUID) -> Truck:
    truck = session.get(Truck, truck_id)
    if truck is None or not truck.is_active:
        raise not_found("Truck")
    return truck


def _spec(truck: Truck) -> TruckSpec:
    return TruckSpec(
        Decimal(str(truck.inner_length_cm)),
        Decimal(str(truck.inner_width_cm)),
        Decimal(str(truck.inner_height_cm)),
        Decimal(str(truck.payload_kg)),
    )


def _loads(rows: list[PendingRow]) -> list[Load]:
    """Planner input. With a package type, its size and weight; without one, the LR's own weight
    spread over its packages, so the load is at least checked against the payload."""
    loads = []
    for lr, pending, item in rows:
        if item is not None:
            dims = (Decimal(str(item.length_cm)), Decimal(str(item.width_cm)), Decimal(str(item.height_cm)))
            unit_weight = Decimal(str(item.unit_weight_kg))
        else:
            dims = None
            unit_weight = lr.weight / lr.packages if lr.weight is not None else None
        loads.append(Load(lr_id=lr.id, pending=pending, unit_dims_cm=dims, unit_weight_kg=unit_weight))
    return loads


def _pct(used: Decimal, capacity: Decimal) -> int:
    return round(used * 100 / capacity)


def _plan_read(spec: TruckSpec, rows: list[PendingRow], result: Plan) -> PlanRead:
    by_id = {lr.id: _pending_lr(lr, pending, item) for lr, pending, item in rows}
    return PlanRead(
        lines=[
            PlanLine(
                lr_id=line.lr_id,
                lr_number=by_id[line.lr_id].lr_number,
                consignee_name=by_id[line.lr_id].consignee_name,
                to_city=by_id[line.lr_id].to_city.upper(),
                pending=by_id[line.lr_id].pending,
                load=line.packages,
                volume_m3=round(line.volume_m3, 2),
                weight_kg=round(line.weight_kg, 2),
            )
            for line in result.lines
        ],
        weight_only=[by_id[i] for i in result.weight_only],
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


def plan(session: Session, truck_id: uuid.UUID, stops: list[str]) -> PlanRead:
    spec = _spec(_truck(session, truck_id))
    rows = _pending_rows(session, cities=stops)
    return _plan_read(spec, rows, plan_load(spec, _loads(rows)))


def _free_trucks(session: Session) -> list[Truck]:
    """Active trucks that are not out on a trip and whose papers have not expired."""
    on_trip = select(Trip.truck_id).where(Trip.status == "dispatched")
    trucks = session.scalars(
        select(Truck).where(Truck.is_active, Truck.id.not_in(on_trip)).order_by(Truck.payload_kg)
    ).all()
    return [
        t for t in trucks
        if not any(expiry is not None and expiry < today() for expiry in (t.insurance_expiry, t.fitness_expiry))
    ]


def suggestions(session: Session) -> list[Suggestion]:
    """Which truck to send where. Pending LRs are grouped by route, so goods for stations one truck
    passes in a single run (Dhamtari, then Jagdalpur) travel together; a city on no route is its own
    group. The group waiting longest picks first. For each group, the smallest free truck that takes
    everything wins; if none can, the one that takes the most packages."""
    rows = _pending_rows(session)
    if not rows:
        return []
    pending_cities = {lr.to_city.upper() for lr, _, _ in rows}
    groups: list[tuple[str | None, list[str]]] = []
    covered: set[str] = set()
    for route in session.scalars(select(Route).where(Route.is_active).order_by(Route.name)):
        stops = [stop for stop in route.stops if stop in pending_cities]
        if stops:
            groups.append((route.name, stops))
            covered.update(stops)
    groups += [(None, [city]) for city in sorted(pending_cities - covered)]
    # A route whose pending stops all lie on a longer suggestion adds nothing.
    groups = [g for g in groups if not any(set(g[1]) < set(other[1]) for other in groups)]

    def group_rows(stops: list[str]) -> list[PendingRow]:
        return [row for row in rows if row[0].to_city.upper() in stops]

    groups.sort(key=lambda g: min(row[0].lr_date for row in group_rows(g[1])))
    free = _free_trucks(session)
    result = []
    for route_name, stops in groups:
        mine = group_rows(stops)
        total = sum(pending for _, pending, _ in mine)
        oldest = (today() - min(lr.lr_date for lr, _, _ in mine)).days
        where = " and ".join(stops) if len(stops) < 3 else f"{', '.join(stops[:-1])} and {stops[-1]}"
        best: tuple[Truck, Plan, int] | None = None
        for truck in free:  # smallest payload first, so the first truck that takes everything is the tightest fit
            candidate = plan_load(_spec(truck), _loads(mine))
            loaded = sum(line.packages for line in candidate.lines)
            if best is None or loaded > best[2]:
                best = (truck, candidate, loaded)
            if loaded == total:
                break
        if best is None or best[2] == 0:
            result.append(
                Suggestion(
                    route_name=route_name, stops=stops, truck_id=None, vehicle_number=None, truck_location=None,
                    plan=None, packages_pending=total, packages_loaded=0, oldest_days_waiting=oldest,
                    reason=f"No free truck can take the goods for {where}.",
                )
            )
            continue
        truck, chosen, loaded = best
        free.remove(truck)
        read = _plan_read(_spec(truck), mine, chosen)
        fill = max(read.volume_used_pct, read.payload_used_pct)
        carried = "all" if loaded == total else f"{loaded} of {total}"
        result.append(
            Suggestion(
                route_name=route_name,
                stops=stops,
                truck_id=truck.id,
                vehicle_number=truck.vehicle_number,
                truck_location=truck.current_station,
                plan=read,
                packages_pending=total,
                packages_loaded=loaded,
                oldest_days_waiting=oldest,
                reason=f"Takes {carried} packages for {where} in one run, {fill}% full."
                + ("" if loaded == total else " The rest waits for the next truck."),
            )
        )
    return result


def _content_hash(session: Session, challan: Challan) -> str:
    """A fingerprint of what the challan says was loaded, chained to the challan issued before it."""
    lines = session.execute(
        select(Lr.lr_number, DispatchLine.packages)
        .join(Lr, Lr.id == DispatchLine.lr_id)
        .where(DispatchLine.challan_id == challan.id)
        .order_by(Lr.lr_number)
    ).all()
    content = {
        "trip": str(challan.trip_id),
        "seq": challan.seq,
        "loaded_at": challan.loaded_at,
        "lines": [[number, packages] for number, packages in lines],
        "prev": challan.prev_hash,
    }
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def seal(session: Session, challan: Challan) -> None:
    """Fix an issued challan's contents. Call once its lines are written."""
    challan.prev_hash = session.scalar(
        select(Challan.content_hash)
        .where(Challan.trip_id == challan.trip_id, Challan.status == "issued", Challan.id != challan.id)
        .order_by(Challan.issued_at.desc())
        .limit(1)
    )
    challan.content_hash = _content_hash(session, challan)
    session.flush()


def is_sealed(session: Session, challan: Challan) -> bool | None:
    """Whether an issued challan still matches its seal. None for a challan that was never sealed
    (not issued yet, or created for a trip that existed before sealing)."""
    if challan.content_hash is None:
        return None
    return _content_hash(session, challan) == challan.content_hash


def _trip_read(session: Session, trip: Trip) -> TripRead:
    truck = session.get_one(Truck, trip.truck_id)
    rows = session.execute(
        select(DispatchLine, Lr, Challan)
        .join(Lr, Lr.id == DispatchLine.lr_id)
        .join(Challan, Challan.id == DispatchLine.challan_id)
        .where(DispatchLine.trip_id == trip.id)
        .order_by(Lr.lr_date, Lr.series_no)
    ).all()
    stops = [
        TripStop(
            city=city,
            lr_count=sum(1 for _, lr, _ in rows if lr.to_city.upper() == city),
            delivered_count=sum(1 for line, lr, _ in rows if lr.to_city.upper() == city and line.delivered_at is not None),
        )
        for city in trip.route
    ]
    delivered = sum(stop.delivered_count for stop in stops)
    return TripRead(
        id=trip.id,
        trip_no=trip.trip_no,
        vehicle_number=truck.vehicle_number,
        destination=trip.destination,
        stops=stops,
        driver_name=trip.driver_name,
        driver_phone=trip.driver_phone,
        status=trip.status,
        progress="delivered" if trip.status == "completed" else "partially_delivered" if delivered else "in_transit",
        next_stop=next((stop.city for stop in stops if stop.delivered_count < stop.lr_count), None),
        dispatched_at=trip.dispatched_at,
        completed_at=trip.completed_at,
        lines=[
            TripLineRead(
                id=line.id,
                lr_id=lr.id,
                lr_number=lr.lr_number,
                consignee_name=lr.consignee_name,
                to_city=lr.to_city.upper(),
                packages=line.packages,
                delivered_at=line.delivered_at,
                challan_number=challan.challan_number,
                loaded_at=challan.loaded_at,
            )
            for line, lr, challan in rows
        ],
    )


def dispatch(session: Session, actor: User, data: DispatchRequest) -> TripRead:
    """Send a truck out on one or more stops. Every LR row is locked while its remaining packages
    are checked, so two dispatchers cannot both load the same packages."""
    truck = _truck(session, data.truck_id)
    for paper, expiry in (("insurance", truck.insurance_expiry), ("fitness certificate", truck.fitness_expiry)):
        if expiry is not None and expiry < today():
            raise conflict(
                f"Truck {truck.vehicle_number} cannot go out: its {paper} expired on {expiry.strftime('%d-%m-%Y')}."
            )
    # Read now: a failed insert below expires every loaded row.
    truck_busy = conflict(f"Truck {truck.vehicle_number} is still on a trip with goods to deliver.")
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
        if lr.to_city.upper() not in data.stops:
            raise conflict(f"LR {lr.lr_number} is for {lr.to_city.upper()}, which is not a stop on this trip.")
        remaining = lr.packages - sent.get(lr.id, 0)
        if wanted[lr.id] > remaining:
            raise conflict(f"LR {lr.lr_number} has only {remaining} packages pending.")
        if lr.ewb_status == "pending":
            raise conflict(
                f"LR {lr.lr_number} needs an e-way bill before it can move. Add the number on the LR first."
            )
    # Entering the vehicle is Part B: from now the bill covers the road and its validity runs.
    for lr in lrs:
        if lr.ewb_status == "awaiting_part_b":
            lr.ewb_status = "active"
            lr.ewb_vehicle_number = truck.vehicle_number
            lr.ewb_valid_until = midnight_after(today() + dt.timedelta(days=validity_days(lr.distance_km) - 1))

    trip = Trip(
        company_id=actor.company_id,
        truck_id=truck.id,
        trip_no=lr_service.take_trip_number(session, actor.company_id),
        route=data.stops,
        destination=data.stops[-1],
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
    # The primary challan: the sealed record of what left the origin.
    primary = Challan(
        company_id=actor.company_id,
        trip_id=trip.id,
        seq=0,
        challan_number=f"CH-{trip.trip_no}",
        loaded_at=lrs[0].from_city.upper(),
        status="issued",
        requested_lines=[{"lr_id": str(lr_id), "packages": packages} for lr_id, packages in wanted.items()],
        requested_by=actor.id,
        issued_at=utcnow(),
    )
    session.add(primary)
    session.flush()
    session.add_all(
        DispatchLine(
            company_id=actor.company_id, trip_id=trip.id, challan_id=primary.id, lr_id=lr_id, packages=packages
        )
        for lr_id, packages in wanted.items()
    )
    session.flush()
    seal(session, primary)
    session.refresh(trip)
    audit.record(
        session,
        company_id=actor.company_id,
        actor_id=actor.id,
        action="trip.dispatch",
        entity="trip",
        entity_id=trip.id,
        detail={"truck": truck.vehicle_number, "stops": data.stops, "lines": {lr.lr_number: wanted[lr.id] for lr in lrs}},
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


def _locked_trip(session: Session, trip_id: uuid.UUID) -> Trip:
    trip = session.get(Trip, trip_id, with_for_update=True)
    if trip is None:
        raise not_found("Trip")
    return trip


def _mark_delivered(session: Session, actor: User, trip: Trip, lines: list[DispatchLine]) -> TripRead:
    """Mark these lines delivered. When the trip's last line is done, the trip completes and the
    truck is free again, standing at the final stop."""
    now = utcnow()
    for line in lines:
        line.delivered_at = now
        line.delivered_by = actor.id
    session.flush()
    undelivered = session.scalar(
        select(func.count())
        .select_from(DispatchLine)
        .where(DispatchLine.trip_id == trip.id, DispatchLine.delivered_at.is_(None))
    )
    if undelivered == 0:
        trip.status = "completed"
        trip.completed_at = now
        session.get_one(Truck, trip.truck_id).current_station = trip.destination
        session.flush()
    audit.record(
        session,
        company_id=actor.company_id,
        actor_id=actor.id,
        action="trip.deliver",
        entity="trip",
        entity_id=trip.id,
        detail={"lines": [str(line.id) for line in lines], "trip_completed": undelivered == 0},
    )
    return _trip_read(session, trip)


def deliver(session: Session, actor: User, trip_id: uuid.UUID, line_id: uuid.UUID) -> TripRead:
    """Mark one LR on a trip as delivered."""
    trip = _locked_trip(session, trip_id)
    line = session.scalar(select(DispatchLine).where(DispatchLine.id == line_id, DispatchLine.trip_id == trip.id))
    if line is None:
        raise not_found("Trip line")
    if line.delivered_at is not None:
        raise conflict("This delivery is already confirmed.")
    return _mark_delivered(session, actor, trip, [line])


def deliver_stop(session: Session, actor: User, trip_id: uuid.UUID, city: str) -> TripRead:
    """Mark every LR for one stop as delivered: the truck has unloaded there and moves on."""
    trip = _locked_trip(session, trip_id)
    lines = session.scalars(
        select(DispatchLine)
        .join(Lr, Lr.id == DispatchLine.lr_id)
        .where(DispatchLine.trip_id == trip.id, func.upper(Lr.to_city) == city.upper(), DispatchLine.delivered_at.is_(None))
    ).all()
    if not lines:
        raise conflict(f"There is nothing left to deliver at {city.upper()} on this trip.")
    return _mark_delivered(session, actor, trip, list(lines))


def undo_delivery(session: Session, actor: User, trip_id: uuid.UUID, line_id: uuid.UUID) -> TripRead:
    """Take back a delivery marked by mistake. The trip goes back on the road if it had completed."""
    trip = _locked_trip(session, trip_id)
    line = session.scalar(select(DispatchLine).where(DispatchLine.id == line_id, DispatchLine.trip_id == trip.id))
    if line is None:
        raise not_found("Trip line")
    if line.delivered_at is None:
        raise conflict("This delivery has not been confirmed, so there is nothing to undo.")
    reopened = trip.status == "completed"
    if reopened and session.scalar(
        select(Trip.id).where(Trip.truck_id == trip.truck_id, Trip.status == "dispatched")
    ) is not None:
        raise conflict("This truck has since gone out on another trip, so its old trip cannot be reopened.")
    delivered_at = line.delivered_at
    line.delivered_at = None
    line.delivered_by = None
    if reopened:
        trip.status = "dispatched"
        trip.completed_at = None
        # Back on the road, so it is no longer standing at the final stop.
        session.get_one(Truck, trip.truck_id).current_station = None
    session.flush()
    audit.record(
        session,
        company_id=actor.company_id,
        actor_id=actor.id,
        action="trip.undo_delivery",
        entity="dispatch_line",
        entity_id=line.id,
        detail={"trip_id": str(trip.id), "was_delivered_at": delivered_at.isoformat(), "trip_reopened": reopened},
    )
    return _trip_read(session, trip)


def load_sheet_rows(session: Session, trip_id: uuid.UUID) -> list[LoadSheetRow]:
    """The truck's cargo in unloading order: by stop, then by LR."""
    trip = session.get_one(Trip, trip_id)
    rows = session.execute(
        select(DispatchLine, Lr, Challan)
        .join(Lr, Lr.id == DispatchLine.lr_id)
        .join(Challan, Challan.id == DispatchLine.challan_id)
        .where(DispatchLine.trip_id == trip_id)
    ).all()
    rows.sort(key=lambda row: (trip.route.index(row[1].to_city.upper()), row[1].lr_date, row[1].series_no))
    result = []
    for line, lr, challan in rows:
        # A to-pay LR split across trucks is collected once, by the first truck that carries it.
        earlier = session.scalar(
            select(func.count())
            .select_from(DispatchLine)
            .join(Trip, Trip.id == DispatchLine.trip_id)
            .where(DispatchLine.lr_id == lr.id, Trip.dispatched_at < trip.dispatched_at)
        )
        collect = lr.freight_by == "ToPay" and earlier == 0
        result.append(
            LoadSheetRow(
                lr_number=lr.lr_number,
                consignor_name=lr.consignor_name,
                consignee_name=lr.consignee_name,
                goods_description=lr.goods_description,
                to_city=lr.to_city.upper(),
                challan_number=challan.challan_number,
                packages=line.packages,
                to_collect=f"Rs {lr.total:,.2f}" if collect else "-",
            )
        )
    return result

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clock import start_of, today
from app.db import get_session
from app.deps import current_user, require_roles
from app.dispatch import additions
from app.dispatch import service as dispatch_service
from app.dispatch.addition_schemas import ChallanRead
from app.dispatch.schemas import PendingDestination
from app.models import Lr, Role, Trip, Truck, User
from app.payments import service as payments_service
from app.payments.schemas import PartyOutstanding
from app.security import utcnow

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class Dashboard(BaseModel):
    date: dt.date
    lrs_today: int
    pending_packages: int
    pending_lrs: int
    trips_on_road: int
    pending_by_destination: list[PendingDestination]


@router.get("", response_model=Dashboard)
def dashboard(_: User = Depends(current_user), session: Session = Depends(get_session)) -> Dashboard:
    pending = dispatch_service.pending_destinations(session)
    return Dashboard(
        date=today(),
        lrs_today=session.scalar(
            select(func.count()).select_from(Lr).where(Lr.lr_date == today(), Lr.status == "confirmed")
        ),
        pending_packages=sum(group.packages for group in pending),
        pending_lrs=sum(group.lr_count for group in pending),
        trips_on_road=session.scalar(select(func.count()).select_from(Trip).where(Trip.status == "dispatched")),
        pending_by_destination=pending,
    )


class TruckOnBoard(BaseModel):
    vehicle_number: str
    # on_trip, or available
    state: str
    # Where an available truck stands; null when that was never recorded.
    location: str | None
    # For a truck on a trip: where it is heading next, its final stop, and how far it has got.
    next_stop: str | None
    destination: str | None
    progress: str | None
    papers_expired: bool


class DayRevenue(BaseModel):
    date: dt.date
    freight: Decimal


class Ranked(BaseModel):
    name: str
    freight: Decimal


class ExpiringBill(BaseModel):
    lr_number: str
    eway_bill_no: str
    vehicle_number: str | None
    valid_until: dt.datetime


class AdminDashboard(BaseModel):
    trips_in_transit: int
    trips_partially_delivered: int
    trips_completed_today: int
    trucks: list[TruckOnBoard]
    freight_today: Decimal
    freight_this_month: Decimal
    last_7_days: list[DayRevenue]
    receivables_outstanding: Decimal
    receivables_overdue: Decimal
    top_debtors: list[PartyOutstanding]
    top_destinations: list[Ranked]
    top_clients: list[Ranked]
    eway_bills_expiring: list[ExpiringBill]
    # Cargo additions still waiting for approval or for the driver, oldest first.
    additions_waiting: list[ChallanRead]


@router.get("/admin", response_model=AdminDashboard)
def admin_dashboard(
    admin: User = Depends(require_roles(Role.ADMIN)), session: Session = Depends(get_session)
) -> AdminDashboard:
    """The owner's view: fleet, trips, freight booked, money owed, and e-way bills about to lapse."""
    day = today()
    month_start = day.replace(day=1)
    open_trips = {trip.vehicle_number: trip for trip in dispatch_service.list_trips(session, status="dispatched", limit=100, offset=0)}
    trucks = []
    for truck in session.scalars(select(Truck).where(Truck.is_active).order_by(Truck.vehicle_number)):
        trip = open_trips.get(truck.vehicle_number)
        trucks.append(
            TruckOnBoard(
                vehicle_number=truck.vehicle_number,
                state="on_trip" if trip else "available",
                location=None if trip else truck.current_station,
                next_stop=trip.next_stop if trip else None,
                destination=trip.destination if trip else None,
                progress=trip.progress if trip else None,
                papers_expired=any(e is not None and e < day for e in (truck.insurance_expiry, truck.fitness_expiry)),
            )
        )

    def freight(*conditions) -> Decimal:
        return session.scalar(select(func.coalesce(func.sum(Lr.total), 0)).where(Lr.status == "confirmed", *conditions))

    def ranked(column) -> list[Ranked]:
        rows = session.execute(
            select(func.upper(column), func.sum(Lr.total))
            .where(Lr.status == "confirmed", Lr.lr_date >= month_start)
            .group_by(func.upper(column))
            .order_by(func.sum(Lr.total).desc())
            .limit(5)
        ).all()
        return [Ranked(name=name, freight=amount) for name, amount in rows]

    by_day = dict(
        session.execute(
            select(Lr.lr_date, func.sum(Lr.total))
            .where(Lr.status == "confirmed", Lr.lr_date > day - dt.timedelta(days=7))
            .group_by(Lr.lr_date)
        ).all()
    )
    owed = payments_service.receivables(session)
    expiring = session.scalars(
        select(Lr)
        .where(Lr.ewb_status == "active", Lr.ewb_valid_until < utcnow() + dt.timedelta(hours=24))
        .order_by(Lr.ewb_valid_until)
        .limit(20)
    )
    return AdminDashboard(
        trips_in_transit=sum(1 for t in open_trips.values() if t.progress == "in_transit"),
        trips_partially_delivered=sum(1 for t in open_trips.values() if t.progress == "partially_delivered"),
        trips_completed_today=session.scalar(
            select(func.count()).select_from(Trip).where(Trip.status == "completed", Trip.completed_at >= start_of(day))
        ),
        trucks=trucks,
        freight_today=freight(Lr.lr_date == day),
        freight_this_month=freight(Lr.lr_date >= month_start),
        last_7_days=[
            DayRevenue(date=d, freight=by_day.get(d, Decimal(0)))
            for d in (day - dt.timedelta(days=n) for n in range(6, -1, -1))
        ],
        receivables_outstanding=owed.outstanding,
        receivables_overdue=owed.overdue,
        top_debtors=owed.parties[:5],
        top_destinations=ranked(Lr.to_city),
        top_clients=ranked(Lr.consignor_name),
        additions_waiting=additions.open_additions(session, admin),
        eway_bills_expiring=[
            ExpiringBill(
                lr_number=lr.lr_number,
                eway_bill_no=lr.eway_bill_no,
                vehicle_number=lr.ewb_vehicle_number,
                valid_until=lr.ewb_valid_until,
            )
            for lr in expiring
        ],
    )

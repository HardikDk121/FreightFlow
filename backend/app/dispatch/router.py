import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import current_user, require_roles
from app.dispatch import service
from app.dispatch.schemas import DispatchRequest, PendingDestination, PendingLr, PlanRead, PlanRequest, TripRead
from app.models import Company, Role, User
from app.reports.pdf import build_table_report

router = APIRouter(tags=["dispatch"])
_dispatcher = require_roles(Role.ADMIN, Role.MANAGER, Role.DISPATCHER)


@router.get("/pending", response_model=list[PendingDestination])
def pending_destinations(
    _: User = Depends(current_user), session: Session = Depends(get_session)
) -> list[PendingDestination]:
    return service.pending_destinations(session)


@router.get("/pending/lrs", response_model=list[PendingLr])
def pending_lrs(
    destination: Annotated[str | None, Query(max_length=30)] = None,
    older_than_days: Annotated[int | None, Query(ge=0, le=3650)] = None,
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> list[PendingLr]:
    return service.pending_lrs(session, destination=destination, older_than_days=older_than_days)


@router.post("/trips/plan", response_model=PlanRead)
def plan_trip(
    body: PlanRequest, _: User = Depends(_dispatcher), session: Session = Depends(get_session)
) -> PlanRead:
    """Suggest what to load for a destination, oldest first, within the truck's space and payload."""
    return service.plan(session, body.truck_id, body.destination)


@router.post("/trips", response_model=TripRead, status_code=status.HTTP_201_CREATED)
def dispatch_trip(
    body: DispatchRequest, actor: User = Depends(_dispatcher), session: Session = Depends(get_session)
) -> TripRead:
    return service.dispatch(session, actor, body)


@router.get("/trips", response_model=list[TripRead])
def list_trips(
    status: Literal["dispatched", "completed"] | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> list[TripRead]:
    return service.list_trips(session, status=status, limit=limit, offset=offset)


@router.get("/trips/{trip_id}", response_model=TripRead)
def get_trip(
    trip_id: uuid.UUID, _: User = Depends(current_user), session: Session = Depends(get_session)
) -> TripRead:
    return service.get_trip(session, trip_id)


@router.post("/trips/{trip_id}/lines/{line_id}/deliver", response_model=TripRead)
def deliver_line(
    trip_id: uuid.UUID,
    line_id: uuid.UUID,
    actor: User = Depends(_dispatcher),
    session: Session = Depends(get_session),
) -> TripRead:
    return service.deliver(session, actor, trip_id, line_id)


@router.post("/trips/{trip_id}/lines/{line_id}/undo-delivery", response_model=TripRead)
def undo_delivery(
    trip_id: uuid.UUID,
    line_id: uuid.UUID,
    actor: User = Depends(require_roles(Role.ADMIN, Role.MANAGER)),
    session: Session = Depends(get_session),
) -> TripRead:
    """Reverse a delivery marked by mistake. Admins and managers only; the reversal is audited."""
    return service.undo_delivery(session, actor, trip_id, line_id)


@router.get(
    "/trips/{trip_id}/load-sheet.pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
def trip_load_sheet(
    trip_id: uuid.UUID, user: User = Depends(current_user), session: Session = Depends(get_session)
) -> Response:
    """What is on the truck, for the driver and the receiving godown: one row per LR, with the
    amount to collect on delivery where freight is to pay."""
    trip = service.get_trip(session, trip_id)
    rows = service.load_sheet_rows(session, trip_id)
    driver = " · ".join(part for part in (trip.driver_name, trip.driver_phone) if part)
    pdf = build_table_report(
        company_name=session.get_one(Company, user.company_id).name.upper(),
        title="LOAD SHEET",
        subtitle=f"{trip.vehicle_number} to {trip.destination} · {trip.dispatched_at.strftime('%d-%m-%Y')}",
        columns=[("#", 8), ("LR No", 24), ("Consignor", 38), ("Consignee", 38), ("Goods", 34), ("Pkgs", 12), ("To collect", 26)],
        rows=[
            [str(n), r.lr_number, r.consignor_name, r.consignee_name, r.goods_description, str(r.packages), r.to_collect]
            for n, r in enumerate(rows, start=1)
        ],
        totals=["", f"{len(rows)} LRs", "", "", "", str(sum(r.packages for r in rows)), ""],
        notes=[
            f"Driver: {driver or '________________________'}",
            "Loaded by: ________________________        Received by: ________________________",
        ],
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="load-sheet-{trip.vehicle_number}.pdf"'},
    )

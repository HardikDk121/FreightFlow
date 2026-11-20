import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Response, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import current_user
from app.dispatch import service
from app.dispatch.schemas import (
    DispatchRequest,
    PendingDestination,
    PendingLr,
    PlanRead,
    PlanRequest,
    Suggestion,
    TripRead,
)
from app.idempotency import IdempotencyHeader, run_once
from app.models import Company, User
from app.permissions import P, require
from app.reports.pdf import build_table_report

router = APIRouter(tags=["dispatch"])
_dispatcher = require(P.DISPATCH)


@router.get("/pending", response_model=list[PendingDestination])
def pending_destinations(
    _: User = Depends(current_user), session: Session = Depends(get_session)
) -> list[PendingDestination]:
    return service.pending_destinations(session)


@router.get("/pending/lrs", response_model=list[PendingLr])
def pending_lrs(
    destination: Annotated[str | None, Query(max_length=400, description="One city, or several separated by commas.")] = None,
    older_than_days: Annotated[int | None, Query(ge=0, le=3650)] = None,
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> list[PendingLr]:
    return service.pending_lrs(session, destination=destination, older_than_days=older_than_days)


@router.post("/trips/plan", response_model=PlanRead)
def plan_trip(
    body: PlanRequest, _: User = Depends(_dispatcher), session: Session = Depends(get_session)
) -> PlanRead:
    """Suggest what to load for the trip's stops, oldest first, within the truck's space and payload."""
    return service.plan(session, body.truck_id, body.stops)


@router.get("/trips/suggestions", response_model=list[Suggestion])
def trip_suggestions(_: User = Depends(_dispatcher), session: Session = Depends(get_session)) -> list[Suggestion]:
    """Which free truck to send on which route, with the load for each. Advice only."""
    return service.suggestions(session)


@router.post("/trips", response_model=TripRead, status_code=status.HTTP_201_CREATED)
def dispatch_trip(
    body: DispatchRequest,
    idempotency_key: IdempotencyHeader = None,
    actor: User = Depends(_dispatcher),
    session: Session = Depends(get_session),
):
    """Send the truck out. Send an Idempotency-Key so a retried dispatch cannot create a second trip."""
    return run_once(session, actor, idempotency_key, "POST /trips", 201, lambda: service.dispatch(session, actor, body))


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


@router.post("/trips/{trip_id}/stops/{city}/deliver", response_model=TripRead)
def deliver_stop(
    trip_id: uuid.UUID,
    city: Annotated[str, Path(max_length=30)],
    actor: User = Depends(_dispatcher),
    session: Session = Depends(get_session),
) -> TripRead:
    """The truck has unloaded at this stop: mark every LR for it delivered. The trip stays open
    while later stops still have goods."""
    return service.deliver_stop(session, actor, trip_id, city)


@router.post("/trips/{trip_id}/lines/{line_id}/undo-delivery", response_model=TripRead)
def undo_delivery(
    trip_id: uuid.UUID,
    line_id: uuid.UUID,
    actor: User = Depends(require(P.TRIP_UNDO_DELIVERY)),
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
        subtitle=f"{trip.vehicle_number} to {' > '.join(s.city for s in trip.stops)} · {trip.dispatched_at.strftime('%d-%m-%Y')}",
        columns=[("#", 7), ("Stop", 22), ("Challan", 20), ("LR No", 20), ("Consignor", 28), ("Consignee", 28), ("Goods", 22), ("Pkgs", 10), ("To collect", 23)],
        rows=[
            [str(n), r.to_city, r.challan_number, r.lr_number, r.consignor_name, r.consignee_name, r.goods_description, str(r.packages), r.to_collect]
            for n, r in enumerate(rows, start=1)
        ],
        totals=["", "", "", f"{len(rows)} LRs", "", "", "", str(sum(r.packages for r in rows)), ""],
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

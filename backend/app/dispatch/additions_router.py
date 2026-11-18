import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import current_user
from app.dispatch import additions
from app.dispatch.addition_schemas import AdditionRequest, ChallanRead, DriverSignOff, VoidRequest
from app.models import User

router = APIRouter(tags=["challans"])


@router.get("/trips/{trip_id}/challans", response_model=list[ChallanRead])
def trip_challans(trip_id: uuid.UUID, user: User = Depends(current_user), session: Session = Depends(get_session)) -> list[ChallanRead]:
    """Every challan on a trip: the primary one from the origin, then each addition, voided ones included."""
    return additions.for_trip(session, user, trip_id)


@router.post("/trips/{trip_id}/additions", response_model=ChallanRead, status_code=status.HTTP_201_CREATED)
def request_addition(
    trip_id: uuid.UUID, body: AdditionRequest, actor: User = Depends(current_user), session: Session = Depends(get_session)
) -> ChallanRead:
    """Ask to load more cargo onto a truck on the road. Nothing moves until it is approved and the driver signs."""
    return additions.request(session, actor, trip_id, body)


@router.get("/challans/open", response_model=list[ChallanRead])
def open_additions(user: User = Depends(current_user), session: Session = Depends(get_session)) -> list[ChallanRead]:
    """Additions waiting for approval or for the driver's signature."""
    return additions.open_additions(session, user)


@router.post("/challans/{challan_id}/approve", response_model=ChallanRead)
def approve_addition(challan_id: uuid.UUID, actor: User = Depends(current_user), session: Session = Depends(get_session)) -> ChallanRead:
    """Approve an addition. Only the person who dispatched the trip can; an admin, if that person asked for it."""
    return additions.approve(session, actor, challan_id)


@router.post("/challans/{challan_id}/void", response_model=ChallanRead)
def void_addition(
    challan_id: uuid.UUID, body: VoidRequest, actor: User = Depends(current_user), session: Session = Depends(get_session)
) -> ChallanRead:
    """Refuse or withdraw an addition before the driver has signed. The challan and its number stay on record."""
    return additions.void(session, actor, challan_id, body.reason)


@router.post("/challans/{challan_id}/sign", response_model=ChallanRead)
def driver_sign_off(
    challan_id: uuid.UUID, body: DriverSignOff, actor: User = Depends(current_user), session: Session = Depends(get_session)
) -> ChallanRead:
    """The driver signs for the packages counted on. This issues and seals the challan."""
    return additions.sign(session, actor, challan_id, body)

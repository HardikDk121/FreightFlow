import datetime as dt

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clock import today
from app.db import get_session
from app.deps import current_user
from app.dispatch import service as dispatch_service
from app.dispatch.schemas import PendingDestination
from app.models import Lr, Trip, User

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

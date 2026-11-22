import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import current_user
from app.masterdata import schemas, service
from app.masterdata.service import MasterDataService
from app.models import User
from app.permissions import P, require
from app.rates import schemas as rates

_editor = require(P.MASTERDATA_EDIT)


def _build(
    prefix: str,
    svc: MasterDataService,
    read: type[BaseModel],
    create: type[BaseModel],
    update: type[BaseModel],
) -> APIRouter:
    """Routes for one master-data resource. Everyone signed in reads; admins and managers write."""
    router = APIRouter(prefix=prefix, tags=["master data"])

    @router.get("", response_model=list[read])
    def list_rows(
        q: Annotated[str | None, Query(max_length=100)] = None,
        include_inactive: bool = False,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
        _: User = Depends(current_user),
        session: Session = Depends(get_session),
    ) -> list[BaseModel]:
        rows = svc.search(session, q=q, include_inactive=include_inactive, limit=limit, offset=offset)
        return [read.model_validate(r) for r in rows]

    @router.get("/{row_id}", response_model=read)
    def get_row(
        row_id: uuid.UUID,
        _: User = Depends(current_user),
        session: Session = Depends(get_session),
    ) -> BaseModel:
        return read.model_validate(svc.get(session, row_id))

    @router.post("", response_model=read, status_code=status.HTTP_201_CREATED)
    def create_row(
        body: create,
        actor: User = Depends(_editor),
        session: Session = Depends(get_session),
    ) -> BaseModel:
        return read.model_validate(svc.create(session, actor, body))

    @router.patch("/{row_id}", response_model=read)
    def update_row(
        row_id: uuid.UUID,
        body: update,
        actor: User = Depends(_editor),
        session: Session = Depends(get_session),
    ) -> BaseModel:
        return read.model_validate(svc.update(session, actor, row_id, body))

    return router


routers = [
    _build("/parties", service.parties, schemas.PartyRead, schemas.PartyCreate, schemas.PartyUpdate),
    _build("/item-types", service.item_types, schemas.ItemTypeRead, schemas.ItemTypeCreate, schemas.ItemTypeUpdate),
    _build("/trucks", service.trucks, schemas.TruckRead, schemas.TruckCreate, schemas.TruckUpdate),
    _build("/stations", service.stations, rates.StationRead, rates.StationCreate, rates.StationUpdate),
    _build("/routes", service.routes, rates.RouteRead, rates.RouteCreate, rates.RouteUpdate),
    _build("/rate-rules", service.rate_rules, rates.RateRuleRead, rates.RateRuleCreate, rates.RateRuleUpdate),
]

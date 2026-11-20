import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app import branches
from app.branches import BranchRead, BranchUpsert
from app.db import get_session
from app.deps import current_user
from app.models import User
from app.permissions import P, require

router = APIRouter(prefix="/branches", tags=["branches"])
_manager = require(P.BRANCHES_MANAGE)


@router.get("", response_model=list[BranchRead])
def list_branches(_: User = Depends(current_user), session: Session = Depends(get_session)) -> list[BranchRead]:
    return [BranchRead.model_validate(b) for b in branches.list_branches(session)]


@router.post("", response_model=BranchRead, status_code=status.HTTP_201_CREATED)
def create_branch(body: BranchUpsert, actor: User = Depends(_manager), session: Session = Depends(get_session)) -> BranchRead:
    return BranchRead.model_validate(branches.create(session, actor, body))


@router.put("/{branch_id}", response_model=BranchRead)
def update_branch(
    branch_id: uuid.UUID, body: BranchUpsert, actor: User = Depends(_manager), session: Session = Depends(get_session)
) -> BranchRead:
    return BranchRead.model_validate(branches.update(session, actor, branch_id, body))

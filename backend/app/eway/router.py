from dataclasses import asdict

from fastapi import APIRouter, Depends

from app.deps import current_user
from app.eway.rules import Consignment, evaluate
from app.eway.schemas import EvaluateRequest, RequirementRead, StateRead
from app.eway.states import STATES
from app.models import User

router = APIRouter(prefix="/eway", tags=["e-way bill"])


@router.get("/states", response_model=list[StateRead])
def list_states(_: User = Depends(current_user)) -> list[StateRead]:
    """GST state codes with each state's intra-state e-way bill limit."""
    return [StateRead(**asdict(state)) for state in sorted(STATES.values(), key=lambda s: s.name)]


@router.post("/evaluate", response_model=RequirementRead)
def evaluate_consignment(body: EvaluateRequest, _: User = Depends(current_user)) -> RequirementRead:
    """Whether this consignment needs an e-way bill, why, and who generates it. Saves nothing."""
    return RequirementRead(**asdict(evaluate(Consignment(**body.model_dump()))))

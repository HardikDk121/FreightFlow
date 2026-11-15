from typing import Annotated

from pydantic import BaseModel, StringConstraints


class ChatRequest(BaseModel):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class ChatResponse(BaseModel):
    answer: str
    # The read-only tool that produced the answer; null when the question was refused or not understood.
    tool: str | None
    # LR numbers the answer was built from, so the person can check it.
    lr_numbers: list[str]

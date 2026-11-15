from typing import Annotated

from pydantic import BaseModel, StringConstraints


class ChatRequest(BaseModel):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    # The LR the conversation is about, so "what is its weight?" works. The app sends the LR
    # number from the previous answer when that answer was about exactly one LR.
    context_lr_number: Annotated[str, StringConstraints(max_length=20)] | None = None


class ChatResponse(BaseModel):
    answer: str
    # The read-only tool that produced the answer; null when the question was refused or not understood.
    tool: str | None
    # LR numbers the answer was built from, so the person can check it.
    lr_numbers: list[str]
    # Questions worth asking next, shown as buttons.
    suggestions: list[str]

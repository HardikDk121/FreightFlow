"""Optional language-model interpreter for the chatbot.

The model's only job is to choose one read-only tool and its arguments, or to answer a greeting
or ask for a missing detail. It is sent the question, today's date, the destination city names
and the LR number under discussion. It never sees LR records: answers are still written by the
tools from the database, so the model cannot invent a figure.

Whatever it returns is validated against the same argument models before anything runs. If the
key is missing, the call fails, or the reply is not a valid tool call, the caller falls back to
the built-in rules in interpreter.py.
"""

import datetime as dt
import logging
from typing import Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.chat.interpreter import Reply, ToolCall
from app.config import get_settings

log = logging.getLogger("freightflow.chat")
_API_URL = "https://api.anthropic.com/v1/messages"
_TIMEOUT = httpx.Timeout(8.0)

LrField = Literal["weight", "value", "charges", "packages", "parties", "eway", "goods", "date", "status"]


class NoArgs(BaseModel):
    pass


class DestinationArgs(BaseModel):
    destination: str = Field(min_length=2, max_length=30, description="Destination city name.")


class OlderThanArgs(BaseModel):
    days: int = Field(ge=0, le=3650, description="Goods that have waited more than this many days.")


class DateArgs(BaseModel):
    date: dt.date = Field(description="The booking date, as YYYY-MM-DD.")


class PartyArgs(BaseModel):
    party: str = Field(min_length=2, max_length=40, description="Part of a consignor or consignee name.")


class GoodsArgs(BaseModel):
    goods: str = Field(min_length=2, max_length=40, description="Part of the goods description, e.g. machinery.")
    packages: int | None = Field(default=None, ge=1, le=99999, description="The number of packages, if the person gave one.")


class LrArgs(BaseModel):
    lr_number: str = Field(min_length=3, max_length=20, description="The LR number, for example RJT-422692.")
    fields: list[LrField] = Field(
        default_factory=list,
        description="The parts of the LR that were asked about. Leave empty for the whole LR.",
    )


class TruckArgs(BaseModel):
    vehicle_number: str = Field(min_length=6, max_length=12, description="Registration with no spaces, e.g. GJ03CW0620.")


# Must list exactly the tools in chat.service.TOOLS; a test checks that.
TOOL_SPECS: dict[str, tuple[str, type[BaseModel]]] = {
    "pending_by_destination": ("LRs still waiting in the godown for one destination city, oldest first.", DestinationArgs),
    "pending_older_than": ("LRs that have waited in the godown more than a number of days.", OlderThanArgs),
    "pending_summary": ("All waiting goods, totalled by destination city.", NoArgs),
    "arrivals_on_date": ("LRs booked on one date, with a count.", DateArgs),
    "recent_lrs": ("The last five LRs booked.", NoArgs),
    "search_lrs": ("LRs whose consignor or consignee name contains some text.", PartyArgs),
    "find_goods": (
        "Past and present LRs found by what was carried (and optionally how many packages), with every "
        "trip that carried them: truck, driver, dates and delivery. Use for questions about history.",
        GoodsArgs,
    ),
    "lr_details": ("One LR by number: parties, goods, weight, value, charges, e-way bill and where the goods are now.", LrArgs),
    "trips_on_road": ("Trucks currently out on a trip and how many of their LRs are delivered.", NoArgs),
    "truck_status": ("Whether one truck is on the road or free.", TruckArgs),
}


def _system_prompt(today: dt.date, cities: frozenset[str], context_lr: str | None) -> str:
    return (
        "You route questions for a transport office app in India. The staff write in English, Hindi or "
        "Gujarati, often mixed and with typos. Words like bilty, builty and consignment mean LR (lorry receipt).\n"
        "Choose exactly one tool that answers the question and call it. Do not answer from your own knowledge: "
        "all facts come from the tools.\n"
        "If the question is a greeting, or cannot be answered without a detail the person left out (for example "
        "which LR), reply with one short sentence in plain English and call no tool.\n"
        "You can only read. If asked to change, cancel, create or dispatch anything, call no tool and say that "
        "changes are made in the app.\n"
        f"Today is {today.isoformat()} ({today.strftime('%A')}).\n"
        f"Destination cities in use: {', '.join(sorted(cities)) or 'none yet'}.\n"
        + (f"The conversation is currently about LR {context_lr}; use it when the question says 'it' or names no LR.\n" if context_lr else "")
    )


def interpret_with_model(
    message: str,
    today: dt.date,
    cities: frozenset[str],
    context_lr: str | None,
    client: httpx.Client | None = None,
) -> ToolCall | Reply | None:
    """The model's choice, or None when no key is set or its answer cannot be used."""
    settings = get_settings()
    if settings.llm_api_key is None:
        return None
    request = {
        "model": settings.llm_model,
        "max_tokens": 300,
        "system": _system_prompt(today, cities, context_lr),
        "tools": [
            {"name": name, "description": description, "input_schema": args.model_json_schema()}
            for name, (description, args) in TOOL_SPECS.items()
        ],
        "messages": [{"role": "user", "content": message}],
    }
    headers = {"x-api-key": settings.llm_api_key, "anthropic-version": "2023-06-01"}
    try:
        http = client or httpx.Client(timeout=_TIMEOUT)
        try:
            response = http.post(_API_URL, json=request, headers=headers)
        finally:
            if client is None:
                http.close()
        response.raise_for_status()
        blocks = response.json()["content"]
        for block in blocks:
            if block["type"] == "tool_use":
                _, args_model = TOOL_SPECS[block["name"]]
                return ToolCall(block["name"], args_model.model_validate(block["input"]).model_dump())
        text = " ".join(block["text"] for block in blocks if block["type"] == "text").strip()
        return Reply(text) if text else None
    except (httpx.HTTPError, KeyError, TypeError, ValueError, ValidationError):
        log.warning("Chat model call failed; using the built-in rules.", exc_info=True)
        return None

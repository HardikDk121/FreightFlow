"""Turns a question into one call to a fixed read-only tool, using keywords only.

This is the baseline interpreter. A language model can replace `interpret` later; it must return
the same ToolCall values, so the tools, permissions and audit log stay exactly as they are.
"""

import datetime as dt
import re
from dataclasses import dataclass, field

REFUSAL = "I can only read information. Please change records in the app."
HELP = (
    "I can tell you what is pending for a destination, what arrived on a date, "
    "which goods have waited more than some days, and the status of an LR."
)

_WRITE = re.compile(r"\b(change|update|delete|remove|cancel|edit|create|add|dispatch|deliver|set|mark|assign)\b")
# The prefix must contain a letter, so a date like 04-10-2026 is not read as an LR number.
_LR_NUMBER = re.compile(r"\b((?=[a-z0-9]*[a-z])[a-z0-9]{1,8}-\d+)\b")
_OLDER = re.compile(r"\b(?:more than|over|older than|above)\s+(\d{1,4})\s*days?\b")
_ARRIVED = re.compile(r"\b(?:came|arrived|booked|received|come)\b(?:\s+in)?(?:\s+on)?\s+(.+)")
_PENDING_FOR = re.compile(r"\b(?:pending|waiting|left)\b.*?\b(?:for|to|in|at)\s+([a-z][a-z ]{1,28}?)\s*\??$")
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


@dataclass(frozen=True)
class ToolCall:
    tool: str
    args: dict = field(default_factory=dict)


def _parse_date(text: str, today: dt.date) -> dt.date | None:
    text = text.strip(" ?.")
    if text.startswith("today"):
        return today
    if text.startswith("yesterday"):
        return today - dt.timedelta(days=1)
    for index, name in enumerate(_WEEKDAYS):
        if text.startswith(name):
            # The most recent such day, today included.
            return today - dt.timedelta(days=(today.weekday() - index) % 7)
    match = re.match(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", text) or None
    if match:
        day, month, year = (int(g) for g in match.groups())
    else:
        match = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
        if not match:
            return None
        year, month, day = (int(g) for g in match.groups())
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


def interpret(message: str, today: dt.date) -> ToolCall | None:
    """The tool call for this question, or None when it asks to change data or is not understood.
    Use `is_write_request` to tell those two apart."""
    text = message.lower().strip()
    if is_write_request(text):
        return None
    if match := _LR_NUMBER.search(text):
        return ToolCall("lr_status", {"lr_number": match.group(1).upper()})
    if match := _OLDER.search(text):
        return ToolCall("pending_older_than", {"days": int(match.group(1))})
    if match := _ARRIVED.search(text):
        if (date := _parse_date(match.group(1), today)) is not None:
            return ToolCall("arrivals_on_date", {"date": date})
    if match := _PENDING_FOR.search(text):
        return ToolCall("pending_by_destination", {"destination": match.group(1).strip()})
    if re.search(r"\b(pending|waiting)\b", text):
        return ToolCall("pending_summary")
    return None


def is_write_request(message: str) -> bool:
    return _WRITE.search(message.lower()) is not None

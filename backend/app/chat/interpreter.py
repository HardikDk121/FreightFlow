"""Turns a question into one call to a fixed read-only tool, using words and patterns only.

It tolerates typos ("confisgment"), everyday synonyms ("bilty", "boxes", "baki") and follow-up
questions about the LR just discussed. It cannot write SQL or change data: it can only name a tool.
A language model can replace `interpret` later; it must return the same values, so the tools,
permissions and audit log stay exactly as they are.
"""

import datetime as dt
import difflib
import re
from dataclasses import dataclass, field

REFUSAL = "I can only read information. Please change records in the app."
HELP = (
    "I did not catch that. I can tell you about an LR (weight, value, charges, status), "
    "what is pending for a city, what was booked on a day, and which trucks are on the road."
)
GREETING = "Hello. Ask me about an LR, pending goods, a day's bookings, or trucks on the road."

_WRITE = re.compile(r"\b(change|update|delete|remove|cancel|edit|create|add|dispatch|deliver|set|mark|assign|modify)\b")
# The prefix must contain a letter, so a date like 04-10-2026 is not read as an LR number.
_LR_NUMBER = re.compile(r"\b((?=[a-z0-9]*[a-z])[a-z0-9]{1,8}-\d+)\b")
_VEHICLE = re.compile(r"\b([a-z]{2}[ -]?\d{1,2}[ -]?[a-z]{1,3}[ -]?\d{4})\b")
_OLDER = re.compile(r"\b(?:more than|over|older than|above|since)\s+(\d{1,4})\s*(?:days?|din)\b")
_PENDING_FOR = re.compile(r"\b(?:pending|waiting|left|baki)\b.*?\b(?:for|to|in|at)\s+([a-z][a-z ]{1,28}?)\s*\??$")
_PARTY = re.compile(r"\b(?:for|of|from|to|by)\s+([a-z][a-z0-9 &.]{2,40}?)\s*\??$")
_DATE = re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b")
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_GREETINGS = {"hi", "hello", "hey", "namaste", "hii", "helo"}

# Everyday words mapped to the one word the rules look for.
_SYNONYMS = {
    "consignment": "lr", "consignments": "lr", "bilty": "lr", "builty": "lr", "bilti": "lr", "lrs": "lr",
    "wt": "weight", "kg": "weight", "kgs": "weight", "vajan": "weight", "wajan": "weight",
    "amount": "total", "worth": "value", "price": "value",
    "package": "packages", "pkg": "packages", "pkgs": "packages", "box": "packages", "boxes": "packages",
    "carton": "packages", "cartons": "packages", "nag": "packages",
    "receiver": "consignee", "sender": "consignor", "party": "consignee",
    "trucks": "truck", "vehicle": "truck", "vehicles": "truck", "lorry": "truck", "gaadi": "truck", "gadi": "truck",
    "trips": "trip", "waiting": "pending", "left": "pending", "remaining": "pending", "baki": "pending",
    "came": "arrived", "come": "arrived", "received": "arrived", "booked": "arrived", "aaya": "arrived",
    "charge": "charges", "bhada": "freight", "aaj": "today", "kal": "yesterday",
    "ewb": "eway", "item": "goods", "items": "goods", "material": "goods", "description": "goods",
    "latest": "recent", "last": "recent", "where": "status", "kahan": "status", "when": "date",
}
_VOCABULARY = set(_SYNONYMS) | set(_SYNONYMS.values()) | set(_WEEKDAYS) | {
    "pending", "weight", "value", "freight", "rate", "hamali", "charges", "total", "packages", "consignee",
    "consignor", "status", "truck", "trip", "road", "today", "yesterday", "arrived", "delivered", "eway",
    "goods", "date", "recent", "lr",
}
# Which part of an LR a word asks about.
_FIELDS = {
    "weight": "weight", "value": "value", "freight": "charges", "rate": "charges", "hamali": "charges",
    "charges": "charges", "total": "charges", "packages": "packages", "consignee": "parties",
    "consignor": "parties", "eway": "eway", "goods": "goods", "date": "date", "status": "status",
}


@dataclass(frozen=True)
class ToolCall:
    tool: str
    args: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Reply:
    """An answer that needs no data: a greeting, or a question back to the person."""

    text: str


def _words(text: str) -> list[str]:
    """Lower-case words with typos corrected and synonyms folded in."""
    text = re.sub(r"e[\s-]*way\s*bill", "eway", text)
    words = []
    for word in re.findall(r"[a-z]+", text):
        if word not in _VOCABULARY and len(word) >= 5:
            close = difflib.get_close_matches(word, _VOCABULARY, n=1, cutoff=0.8)
            word = close[0] if close else word
        words.append(_SYNONYMS.get(word, word))
    return words


def _find_date(text: str, words: list[str], today: dt.date) -> dt.date | None:
    if "today" in words:
        return today
    if "yesterday" in words:
        return today - dt.timedelta(days=1)
    for index, name in enumerate(_WEEKDAYS):
        if name in words:
            # The most recent such day, today included.
            return today - dt.timedelta(days=(today.weekday() - index) % 7)
    if match := _DATE.search(text):
        day, month, year = (int(g) for g in match.groups())
    elif match := _ISO_DATE.search(text):
        year, month, day = (int(g) for g in match.groups())
    else:
        return None
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


def is_write_request(message: str) -> bool:
    return _WRITE.search(message.lower()) is not None


def interpret(
    message: str,
    today: dt.date,
    cities: frozenset[str] = frozenset(),
    context_lr: str | None = None,
) -> ToolCall | Reply | None:
    """What to do with this question: call a tool, reply without data, or None when it asks to
    change data or is not understood (`is_write_request` tells those two apart).

    `cities` are the destinations that exist in this company's LRs, lower-case.
    `context_lr` is the LR the conversation is already about, if any.
    """
    text = message.lower().strip()
    if is_write_request(text):
        return None
    words = _words(text)
    fields = sorted({_FIELDS[w] for w in words if w in _FIELDS})
    date = _find_date(text, words, today)
    city = next((c for c in sorted(cities, key=len, reverse=True) if re.search(rf"\b{re.escape(c)}\b", text)), None)

    if match := _LR_NUMBER.search(text):
        return ToolCall("lr_details", {"lr_number": match.group(1).upper(), "fields": fields})
    if match := _VEHICLE.search(text):
        return ToolCall("truck_status", {"vehicle_number": re.sub(r"[ -]", "", match.group(1)).upper()})
    if match := _OLDER.search(text):
        return ToolCall("pending_older_than", {"days": int(match.group(1))})
    if "pending" in words:
        if city:
            return ToolCall("pending_by_destination", {"destination": city})
        if match := _PENDING_FOR.search(text):
            return ToolCall("pending_by_destination", {"destination": match.group(1).strip()})
        return ToolCall("pending_summary")
    if {"truck", "trip", "road"} & set(words):
        return ToolCall("trips_on_road")
    if date is not None and {"arrived", "lr"} & set(words):
        return ToolCall("arrivals_on_date", {"date": date})
    # A follow-up such as "and its weight?" is about the LR just discussed.
    if fields and context_lr and city is None:
        return ToolCall("lr_details", {"lr_number": context_lr.upper(), "fields": fields})
    if city:
        return ToolCall("pending_by_destination", {"destination": city})
    if "recent" in words and "lr" in words:
        return ToolCall("recent_lrs")
    if fields:
        return Reply("Which LR do you mean? Ask like this: weight of LR-1.")
    if "lr" in words or {"consignee", "consignor"} & set(words):
        if match := _PARTY.search(text):
            return ToolCall("search_lrs", {"party": match.group(1).strip()})
    if set(re.findall(r"[a-z]+", text)) & _GREETINGS:
        return Reply(GREETING)
    return None

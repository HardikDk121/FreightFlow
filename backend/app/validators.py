"""Shared input rules. Every value is trimmed and normalised first; every rejection explains itself in
plain words (never a regex or a schema detail). The Flutter app applies the same rules in
lib/validation.dart, so most mistakes are caught before a request is sent."""

import re
from functools import lru_cache
from pathlib import Path
from typing import Annotated, ClassVar

from pydantic import AfterValidator, BaseModel, BeforeValidator, StringConstraints, model_validator


def _strip(value):
    return value.strip() if isinstance(value, str) else value


def _collapse(value: str) -> str:
    """Trim and turn runs of spaces into one."""
    return re.sub(r"\s+", " ", value.strip())


# ------------------------------------------------------------------ GSTIN

_GSTIN = re.compile(r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]")
_GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
# State and union-territory codes in use (01 to 38), plus 97 (other territory) and 99 (centre jurisdiction).
_GST_STATES = {f"{n:02d}" for n in range(1, 39)} | {"97", "99"}


def gstin_check_digit(first14: str) -> str:
    """The 15th character of a GSTIN: a mod-36 checksum over the first 14."""
    total = 0
    for i, ch in enumerate(first14):
        product = _GSTIN_CHARS.index(ch) * (2 if i % 2 else 1)
        total += product // 36 + product % 36
    return _GSTIN_CHARS[(36 - total % 36) % 36]


def _gstin(value: str) -> str:
    value = re.sub(r"\s", "", value).upper()
    if not _GSTIN.fullmatch(value):
        raise ValueError("Enter a valid 15-character GSTIN, like 24AABCR4141H1ZQ.")
    if value[:2] not in _GST_STATES:
        raise ValueError("The GSTIN's first two digits are not an Indian state code.")
    if gstin_check_digit(value[:14]) != value[14]:
        raise ValueError("This GSTIN's last character does not match; check it for a typing mistake.")
    return value


# ------------------------------------------------------------------ phone

def _phone(value: str) -> str:
    """Indian mobile numbers are stored as 10 digits (6, 7, 8 or 9 first). Numbers from other
    countries are stored with their code, like +971501234567."""
    raw = re.sub(r"[\s()\-.]", "", value)
    if raw.startswith("+") and not raw.startswith("+91"):
        if not re.fullmatch(r"\+[1-9][0-9]{7,14}", raw):
            raise ValueError("Enter a valid phone number with its country code.")
        return raw
    digits = raw.removeprefix("+91")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if not re.fullmatch(r"[6-9][0-9]{9}", digits):
        raise ValueError("Enter a valid 10-digit mobile number starting with 6, 7, 8 or 9.")
    return digits


normalize_phone = _phone


# ------------------------------------------------------------------ names and places

# Letters in any script, digits, and the punctuation business names use.
_BUSINESS_CHARS = re.compile(r"[\w\s&.,'()/@#+\-]+")


def _business_name(value: str) -> str:
    value = _collapse(value)
    if len(value) < 2 or not any(ch.isalpha() for ch in value):
        raise ValueError("Must be at least 2 characters and cannot contain only numbers or symbols.")
    if not _BUSINESS_CHARS.fullmatch(value):
        raise ValueError("Use letters, numbers, spaces and . , & ' - / ( ) # only.")
    return value


def _person_name(value: str) -> str:
    value = _collapse(value)
    if len(value) < 2:
        raise ValueError("Enter the full name.")
    if not re.fullmatch(r"[^\W\d_]+(?:[ .'\-]+[^\W\d_]+)*\.?", value):
        raise ValueError("Use letters, spaces, hyphens and apostrophes only.")
    return value


def _address(value: str) -> str:
    value = "\n".join(_collapse(line) for line in value.strip().splitlines() if line.strip())
    if not value:
        raise ValueError("Enter the address, or leave it empty.")
    if not any(ch.isalpha() for ch in value):
        raise ValueError("An address must contain letters, not only numbers or symbols.")
    return value


def city(value: str) -> str:
    """A city or town: letters first, then letters, spaces, dots, hyphens or apostrophes. Upper-cased."""
    value = _collapse(value).upper()
    if not re.fullmatch(r"[^\W\d_][^\W\d_ .'\-]*(?:[ .'\-]+[^\W\d_]+)*\.?", value):
        raise ValueError("Enter a city name using letters only, like RAJKOT.")
    if len(value) < 2 or len(value) > 30:
        raise ValueError("A city name is 2 to 30 letters.")
    return value


def _pan(value: str) -> str:
    value = re.sub(r"\s", "", value).upper()
    if not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", value):
        raise ValueError("Enter a valid 10-character PAN, like ABCDE1234F.")
    return value


def _digits(name: str, *lengths: int):
    def check(value: str) -> str:
        value = re.sub(r"\s", "", value)
        if not (value.isdigit() and len(value) in lengths):
            shown = " or ".join(str(n) for n in lengths)
            raise ValueError(f"Enter a valid {name}: {shown} digits.")
        return value

    return check


def _enrolment(value: str) -> str:
    value = re.sub(r"\s", "", value).upper()
    if not re.fullmatch(r"[0-9A-Z]{15}", value):
        raise ValueError("Enter the 15-character enrolment ID from ENR-03.")
    return value


# ------------------------------------------------------------------ passwords

MIN_PASSWORD = 12
MAX_PASSWORD = 128


@lru_cache
def _common_passwords() -> frozenset[str]:
    path = Path(__file__).parent / "auth" / "common_passwords.txt"
    return frozenset(line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line and not line.startswith("#"))


def password_problem(password: str) -> str | None:
    """Why a new password is too weak, or None. Length and guessability, not character-class rules:
    passphrases with spaces and any Unicode are welcome."""
    if len(password) < MIN_PASSWORD:
        return f"Use at least {MIN_PASSWORD} characters. A short phrase of a few words is easy to remember."
    if len(password) > MAX_PASSWORD:
        return f"Use at most {MAX_PASSWORD} characters."
    if not password.strip():
        return "The password cannot be only spaces."
    compact = password.replace(" ", "")
    if compact.isdigit():
        return "Don't use only numbers; add some words."
    if compact.isalpha() and compact.isascii() and len(set(compact.lower())) < 6:
        return "Too easy to guess. Use a few different words."
    if len(set(password)) <= 3:
        return "Too easy to guess: it repeats the same few characters."
    lower = password.lower()
    common = _common_passwords()
    base = re.sub(r"[\d\W_]+$", "", lower)  # "password@2026" -> "password"
    if lower in common or (len(base) >= 4 and base in common and len(base) >= len(lower) - 6):
        return "This is one of the most common passwords. Choose something less predictable."
    for seq in ("0123456789", "abcdefghijklmnopqrstuvwxyz", "qwertyuiop", "asdfghjkl", "1qaz2wsx3edc", "q1w2e3r4t5y6"):
        if lower in seq or lower in seq * 2:
            return "Too easy to guess: it is a keyboard or alphabet sequence."
    return None


def _password(value: str) -> str:
    problem = password_problem(value)
    if problem:
        raise ValueError(problem)
    return value


Gstin = Annotated[str, AfterValidator(_gstin)]
Phone = Annotated[str, AfterValidator(_phone)]
Pan = Annotated[str, AfterValidator(_pan)]
BusinessName = Annotated[str, StringConstraints(max_length=200), AfterValidator(_business_name)]
PersonName = Annotated[str, StringConstraints(max_length=100), AfterValidator(_person_name)]
Address = Annotated[str, StringConstraints(max_length=300), AfterValidator(_address)]
City = Annotated[str, BeforeValidator(_strip), StringConstraints(max_length=60), AfterValidator(city)]
HsnCode = Annotated[str, AfterValidator(_digits("HSN code", 4, 6, 8))]
EwayBillNo = Annotated[str, AfterValidator(_digits("e-way bill number", 12))]
EnrolmentId = Annotated[str, AfterValidator(_enrolment)]
# Older free-text names (goods descriptions, labels) keep the plain rule: trimmed, not blank.
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
# A password being set now. Signing in still accepts any stored password.
NewPassword = Annotated[str, AfterValidator(_password)]
Password = Annotated[str, StringConstraints(min_length=1, max_length=MAX_PASSWORD)]


class PatchModel(BaseModel):
    """Base for PATCH bodies. Fields in `not_nullable` may be omitted but not set to null."""

    not_nullable: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def _reject_nulls(self) -> "PatchModel":
        nulled = sorted(f for f in self.model_fields_set & self.not_nullable if getattr(self, f) is None)
        if nulled:
            raise ValueError(f"These fields cannot be null: {', '.join(nulled)}.")
        return self

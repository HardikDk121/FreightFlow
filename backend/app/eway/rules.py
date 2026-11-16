"""Whether a consignment needs an e-way bill under Rule 138 of the CGST Rules, who must generate
it, whether Part B is needed, and how long it stays valid.

Pure functions: no database and no clock. This decides and explains; it does not file anything
with the e-way bill portal. It is an aid for the booking clerk, not legal advice.
"""

import math
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from app.eway.states import INTER_STATE_THRESHOLD, STATES

SHORT_HAUL_KM = 50
KM_PER_VALIDITY_DAY = 200


class Category(StrEnum):
    REGULAR = "regular"
    JOB_WORK = "job_work"  # principal to job worker
    HANDICRAFT = "handicraft"  # handicraft goods sent by a dealer exempt from registration
    HOUSEHOLD_EFFECTS = "household_effects"  # used personal and household effects
    EXEMPT_GOODS = "exempt_goods"  # goods listed in the Annexure to Rule 138(14)


class Leg(StrEnum):
    DIRECT = "direct"
    CONSIGNOR_TO_HUB = "consignor_to_hub"
    HUB_TO_CONSIGNEE = "hub_to_consignee"


class Party(StrEnum):
    CONSIGNOR = "consignor"
    CONSIGNEE = "consignee"
    TRANSPORTER = "transporter"


@dataclass(frozen=True)
class Consignment:
    value: Decimal | None  # invoice value including tax
    from_state: str
    to_state: str
    category: Category
    consignor_registered: bool
    consignee_registered: bool
    distance_km: int | None
    leg: Leg


@dataclass(frozen=True)
class Requirement:
    # True or False once it can be decided; None when the goods value is still missing.
    required: bool | None
    rule: str
    reason: str
    responsible: Party | None = None
    part_b_required: bool = False
    validity_days: int | None = None
    notes: list[str] = field(default_factory=list)


def _rupees(amount: Decimal) -> str:
    """50000 -> "Rs 50,000", 100000 -> "Rs 1,00,000" (Indian digit grouping)."""
    digits = f"{int(amount)}"
    head, tail = digits[:-3], digits[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return "Rs " + ",".join([g for g in [head, *groups] if g] + [tail])


def validity_days(distance_km: int) -> int:
    """One day for every 200 km or part of it (Rule 138(10), cargo that is not over-dimensional)."""
    return max(1, math.ceil(distance_km / KM_PER_VALIDITY_DAY))


def evaluate(c: Consignment) -> Requirement:
    inter_state = c.from_state != c.to_state
    state = STATES[c.from_state]

    if c.category == Category.HOUSEHOLD_EFFECTS:
        return Requirement(
            required=False,
            rule="Rule 138(14)",
            reason="Used personal and household effects are exempt at any value.",
            notes=["Keep the owner's signed declaration and packing list with the goods."],
        )
    if c.category == Category.EXEMPT_GOODS:
        return Requirement(
            required=False,
            rule="Rule 138(14)",
            reason="Goods listed in the Annexure to Rule 138(14) are exempt at any value.",
        )

    notes = []
    if inter_state and c.category in (Category.JOB_WORK, Category.HANDICRAFT):
        kind = "goods sent to a job worker" if c.category == Category.JOB_WORK else "handicraft goods from an exempt dealer"
        rule, reason = "Rule 138(1), provisos", f"Inter-state {kind} need an e-way bill at any value."
    else:
        threshold = INTER_STATE_THRESHOLD if inter_state else state.intra_state_threshold
        scope = "inter-state" if inter_state else f"movement within {state.name}"
        if not inter_state and state.note:
            notes.append(f"{state.name}: {state.note} Check whether that applies here.")
        if c.value is None:
            return Requirement(
                required=None,
                rule="Rule 138(1)",
                reason=f"Enter the goods value. The limit for {scope} is {_rupees(threshold)}.",
                notes=notes,
            )
        if c.value <= threshold:
            return Requirement(
                required=False,
                rule="Rule 138(1)",
                reason=f"The value does not exceed the {_rupees(threshold)} limit for {scope}.",
                notes=notes,
            )
        rule, reason = "Rule 138(1)", f"The value exceeds the {_rupees(threshold)} limit for {scope}."

    # Who generates it (Rule 138(1) to 138(3)).
    if c.consignor_registered:
        responsible = Party.CONSIGNOR
    elif c.consignee_registered:
        responsible = Party.CONSIGNEE
        notes.append("The sender is unregistered, so the registered consignee is treated as causing the movement.")
    else:
        responsible = Party.TRANSPORTER
        notes.append(
            "Neither party is registered. The transporter generates it, or the sender can with an "
            "enrolment ID from Form GST ENR-03."
        )

    # Part B can be skipped only on a short first or last leg inside one state (Rule 138(3), provisos).
    short_leg = (
        not inter_state
        and c.leg != Leg.DIRECT
        and c.distance_km is not None
        and c.distance_km < SHORT_HAUL_KM
    )
    if short_leg:
        notes.append(f"Part B is not needed: this leg is within the state and under {SHORT_HAUL_KM} km.")
    return Requirement(
        required=True,
        rule=rule,
        reason=reason,
        responsible=responsible,
        part_b_required=not short_leg,
        validity_days=validity_days(c.distance_km) if c.distance_km is not None else None,
        notes=notes,
    )

"""GST state codes and each state's e-way bill threshold for movement within the state.

Inter-state movement is Rs 50,000 everywhere. Intra-state limits are set by state notification
and do change (West Bengal moved from Rs 1,00,000 to Rs 50,000 on 1 June 2026), so this file
is the one place to update. Where a state's limit could not be confirmed it is left at
Rs 50,000: the stricter figure asks for an e-way bill that may not be needed, never the reverse.
"""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

REVIEWED_ON = dt.date(2026, 11, 15)
INTER_STATE_THRESHOLD = Decimal(50_000)
_STANDARD = Decimal(50_000)
_HIGHER = Decimal(100_000)


@dataclass(frozen=True)
class State:
    code: str
    name: str
    intra_state_threshold: Decimal = _STANDARD
    # A state rule this engine does not apply, shown to the clerk so a person can judge.
    note: str | None = None


_STATES = [
    State("01", "Jammu and Kashmir"),
    State("02", "Himachal Pradesh"),
    State("03", "Punjab"),
    State("04", "Chandigarh"),
    State("05", "Uttarakhand"),
    State("06", "Haryana"),
    State("07", "Delhi", _HIGHER),
    State("08", "Rajasthan", _HIGHER, "Movement within one city has a Rs 2,00,000 limit."),
    State("09", "Uttar Pradesh"),
    State("10", "Bihar", _HIGHER),
    State("11", "Sikkim"),
    State("12", "Arunachal Pradesh"),
    State("13", "Nagaland"),
    State("14", "Manipur"),
    State("15", "Mizoram"),
    State("16", "Tripura"),
    State("17", "Meghalaya"),
    State("18", "Assam"),
    State("19", "West Bengal", _STANDARD, "Intra-state job work is exempt."),
    State("20", "Jharkhand", _HIGHER, "Specified goods keep the Rs 50,000 limit."),
    State("21", "Odisha"),
    State("22", "Chhattisgarh"),
    State("23", "Madhya Pradesh", _HIGHER, "No e-way bill for movement within one district."),
    State("24", "Gujarat", _STANDARD, "Movement within one city and some textile job work are exempt."),
    State("26", "Dadra and Nagar Haveli and Daman and Diu"),
    State("27", "Maharashtra", _HIGHER),
    State("29", "Karnataka"),
    State("30", "Goa"),
    State("31", "Lakshadweep"),
    State("32", "Kerala", _STANDARD, "Gold and precious stones have their own limit."),
    State("33", "Tamil Nadu", _HIGHER),
    State("34", "Puducherry"),
    State("35", "Andaman and Nicobar Islands"),
    State("36", "Telangana"),
    State("37", "Andhra Pradesh"),
    State("38", "Ladakh"),
]
STATES: dict[str, State] = {state.code: state for state in _STATES}

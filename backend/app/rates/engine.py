"""Freight from the rate matrix. Pure functions: no database.

Chargeable weight is packages x weight per package, unless a total is given to override it
(for example a weighbridge figure). Three ways to charge:

  per_kg            chargeable weight x (rate + the station's surcharge)        bearings
  per_package_slab  a fixed amount per package, by what one package weighs      halka maal
  per_unit          a fixed amount per package, whatever it weighs              rolls, sheets

The station surcharge is per kg of chargeable weight in every case.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

_PAISE = Decimal("0.01")


class PricingError(Exception):
    """The inputs or the rate matrix cannot produce a freight; the message says what to fix."""


@dataclass(frozen=True)
class Rule:
    method: str
    rate: Decimal | None
    # (up to this many kg per package, amount per package), in any order
    slabs: tuple[tuple[Decimal, Decimal], ...] = ()


@dataclass(frozen=True)
class Quote:
    freight: Decimal
    chargeable_weight: Decimal | None
    # The all-in per-kg rate, when the goods are charged by weight.
    rate_per_kg: Decimal | None
    explanation: list[str]


def _num(value: Decimal) -> str:
    return f"{value.normalize():f}"


def chargeable_weight(packages: int, weight_per_package: Decimal | None, total_weight: Decimal | None) -> Decimal | None:
    if total_weight is not None:
        return total_weight
    return packages * weight_per_package if weight_per_package is not None else None


def quote(
    rule: Rule,
    surcharge_per_kg: Decimal,
    packages: int,
    weight_per_package: Decimal | None,
    total_weight: Decimal | None,
) -> Quote:
    weight = chargeable_weight(packages, weight_per_package, total_weight)
    lines = []
    if weight is not None:
        lines.append(
            f"Chargeable weight {_num(weight)} kg (given as the total)"
            if total_weight is not None
            else f"Chargeable weight {packages} packages × {_num(weight_per_package)} kg = {_num(weight)} kg"
        )

    if rule.method == "per_kg":
        if weight is None:
            raise PricingError("Enter the weight per package or the total weight.")
        rate = rule.rate + surcharge_per_kg
        freight = weight * rate
        lines.append(
            f"Rs {_num(rule.rate)} per kg"
            + (f" + Rs {_num(surcharge_per_kg)} station surcharge = Rs {_num(rate)} per kg" if surcharge_per_kg else "")
        )
        lines.append(f"{_num(weight)} kg × Rs {_num(rate)} = Rs {_num(freight)}")
        return Quote(freight.quantize(_PAISE, ROUND_HALF_UP), weight, rate.quantize(_PAISE), lines)

    if rule.method == "per_package_slab":
        if weight_per_package is None:
            raise PricingError("Enter the weight per package: this rate depends on the size of one package.")
        slab = next(((limit, amount) for limit, amount in sorted(rule.slabs) if weight_per_package <= limit), None)
        if slab is None:
            raise PricingError(
                f"No slab covers a {_num(weight_per_package)} kg package. Add one to this rate in the rate matrix."
            )
        per_package = slab[1]
        lines.append(f"A package up to {_num(slab[0])} kg is Rs {_num(per_package)}")
    else:  # per_unit
        per_package = rule.rate
        lines.append(f"Rs {_num(per_package)} per package")

    freight = packages * per_package
    lines.append(f"{packages} packages × Rs {_num(per_package)} = Rs {_num(freight)}")
    if surcharge_per_kg:
        if weight is None:
            raise PricingError("Enter the weight: this station adds a surcharge per kg.")
        surcharge = weight * surcharge_per_kg
        freight += surcharge
        lines.append(f"Station surcharge {_num(weight)} kg × Rs {_num(surcharge_per_kg)} = Rs {_num(surcharge)}")
    return Quote(freight.quantize(_PAISE, ROUND_HALF_UP), weight, None, lines)

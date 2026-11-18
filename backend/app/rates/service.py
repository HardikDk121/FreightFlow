from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import RateRule, Station
from app.rates.engine import PricingError, Rule, quote
from app.rates.schemas import QuoteRead, QuoteRequest


def goods_classes(session: Session) -> list[str]:
    return list(session.scalars(select(RateRule.goods_class).where(RateRule.is_active).distinct().order_by(RateRule.goods_class)))


def price(session: Session, data: QuoteRequest) -> QuoteRead:
    """Find the destination's station, then the rule for this class of goods in its zone, and price it."""
    station = session.scalar(select(Station).where(func.lower(Station.name) == data.to_city.lower(), Station.is_active))
    if station is None:
        raise AppError(422, "no_station", f"{data.to_city} is not in the station list. Add it in the rate matrix.")
    rule = session.scalar(
        select(RateRule).where(
            func.lower(RateRule.goods_class) == data.goods_class.lower(),
            func.lower(RateRule.zone) == station.zone.lower(),
            RateRule.is_active,
        )
    )
    if rule is None:
        raise AppError(422, "no_rate", f"There is no {data.goods_class} rate for the {station.zone} zone.")
    try:
        result = quote(
            Rule(
                method=rule.method,
                rate=Decimal(str(rule.rate)) if rule.rate is not None else None,
                slabs=tuple((Decimal(str(s["up_to_kg"])), Decimal(str(s["amount"]))) for s in rule.slabs or ()),
            ),
            Decimal(str(station.surcharge_per_kg)),
            data.packages,
            data.weight_per_package,
            data.total_weight,
        )
    except PricingError as exc:
        raise AppError(422, "cannot_price", str(exc)) from exc
    return QuoteRead(
        rate_rule_id=rule.id,
        freight=result.freight,
        chargeable_weight=result.chargeable_weight,
        rate_per_kg=result.rate_per_kg,
        explanation=[f"{rule.goods_class} to {station.name} ({station.zone} zone)", *result.explanation],
    )

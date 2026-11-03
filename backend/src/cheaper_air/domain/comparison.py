import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from cheaper_air.domain.models import ComparisonGroup, ExcludedOffer, Offer, RankedOffer, SearchCriteria
from cheaper_air.providers.mock_fx import MockFxProvider


def equivalence_key(offer: Offer) -> str:
    segments = [dict(s.model_dump(mode="json"), departure_at=s.departure_at.astimezone(timezone.utc).isoformat(),
                     arrival_at=s.arrival_at.astimezone(timezone.utc).isoformat()) for s in offer.segments]
    value = {"segments": segments, "conditions": offer.conditions.model_dump(mode="json"), "adults": offer.adults}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:16]


def compare(offers: list[Offer], criteria: SearchCriteria, now: datetime, fx: MockFxProvider):
    buckets: dict[str, list[Offer]] = {}
    excluded = []
    for offer in offers:
        reasons = []
        conditions = offer.conditions
        if offer.market not in criteria.markets:
            reasons.append("UNREQUESTED_MARKET")
        if offer.expires_at <= now or offer.observed_at > now:
            reasons.append("INVALID_OFFER_TIME")
        if offer.mandatory_fees_included is not True:
            reasons.append("UNKNOWN_MANDATORY_FEES")
        if (conditions.fare_product is None or conditions.checked_baggage is None or conditions.cabin_baggage is None
                or conditions.refundable is None or conditions.changeable is None
                or (conditions.changeable and conditions.change_penalty is None)
                or (conditions.refundable and conditions.refund_penalty is None)):
            reasons.append("UNKNOWN_FARE_CONDITIONS")
        bag = conditions.checked_baggage
        required = criteria.checked_baggage
        if bag and (bag.pieces < required.pieces or (required.pieces > 0 and bag.weight_kg < required.weight_kg)):
            reasons.append("INSUFFICIENT_BAGGAGE")
        if offer.total.currency not in fx.rates:
            reasons.append("MISSING_FX_RATE")
        # Validate the requested itinerary before grouping provider output.
        expected = [(criteria.origin, criteria.destination, criteria.departure_date)]
        if criteria.return_date:
            expected.append((criteria.destination, criteria.origin, criteria.return_date))
        actual = [(s.origin, s.destination, s.departure_at.date()) for s in offer.segments]
        if actual != expected or conditions.cabin != criteria.cabin or offer.adults != criteria.adults:
            reasons.append("ITINERARY_MISMATCH")
        if reasons:
            excluded.append(ExcludedOffer(offer_id=offer.id, reason_codes=reasons))
        else:
            buckets.setdefault(equivalence_key(offer), []).append(offer)
    groups = []
    for key, items in sorted(buckets.items()):
        ordered = sorted(items, key=lambda o: (fx.convert(o.total), o.id))
        baseline = next((o for o in ordered if o.market == criteria.baseline_market), None)
        base = fx.convert(baseline.total) if baseline else None
        ranked = []
        for offer in ordered:
            total = fx.convert(offer.total)
            saving = base - total if base is not None else None
            percent = (saving / base * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if base is not None else None
            ranked.append(RankedOffer(offer_id=offer.id, total_eur=total, savings_eur=saving, savings_percent=percent))
        groups.append(ComparisonGroup(id=key, baseline_offer_id=baseline.id if baseline else None, offers=ranked))
    return groups, excluded

from datetime import datetime, time, timedelta, timezone
from cheaper_air.domain.models import Baggage, FareConditions, Money, Offer, SearchCriteria, Segment


class MockFlightProvider:
    """Synthetic scheduled examples. VNO–LHR and VNO–MIA are supported; no inventory claim."""
    supported_markets = {"LT", "GB", "US"}

    supported_routes = {("VNO", "LHR"), ("VNO", "MIA")}

    async def search(self, criteria: SearchCriteria, now: datetime) -> list[Offer]:
        if (criteria.origin, criteria.destination) not in self.supported_routes:
            return []
        segments = []
        legs = [(criteria.origin, criteria.destination, criteria.departure_date, "100")]
        if criteria.return_date:
            legs.append((criteria.destination, criteria.origin, criteria.return_date, "101"))
        for origin, destination, day, number in legs:
            departure = datetime.combine(day, time(10), tzinfo=timezone.utc)
            segments.append(Segment(origin=origin, destination=destination, departure_at=departure,
                                    arrival_at=departure + timedelta(hours=13 if criteria.destination == "MIA" else 3), marketing_carrier="ZZ",
                                    operating_carrier="ZZ", flight_number=number))
        conditions = FareConditions(fare_product="MOCK-STANDARD", checked_baggage=Baggage(pieces=1, weight_kg=23),
                                   cabin_baggage=Baggage(pieces=1, weight_kg=8), refundable=False, changeable=False)
        prices = {"LT": ("240", "EUR"), "GB": ("180", "GBP"), "US": ("245", "USD")}
        if criteria.destination == "MIA":
            prices = {"LT": ("820", "EUR"), "GB": ("640", "GBP"), "US": ("790", "USD")}
        offers = []
        for market in criteria.markets:
            if market not in prices:
                continue
            amount, currency = prices[market]
            offers.append(Offer(id=f"mock-{market.lower()}-standard", segments=segments, market=market,
                                total=Money(amount=amount, currency=currency), conditions=conditions,
                                mandatory_fees_included=True, observed_at=now, expires_at=now + timedelta(minutes=30)))
        if "GB" in criteria.markets:
            light = conditions.model_copy(update={"fare_product": "MOCK-LIGHT", "checked_baggage": Baggage(pieces=0, weight_kg=0)})
            offers.append(Offer(id="mock-gb-light", segments=segments, market="GB", total=Money(amount="580" if criteria.destination == "MIA" else "150", currency="GBP"),
                                conditions=light, mandatory_fees_included=True, observed_at=now,
                                expires_at=now + timedelta(minutes=30)))
        return offers

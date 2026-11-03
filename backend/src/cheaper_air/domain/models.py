from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Baggage(StrictModel):
    pieces: int = Field(ge=0, le=3)
    weight_kg: int = Field(ge=0, le=40)


class SearchCriteria(StrictModel):
    origin: str = Field(pattern=r"^[A-Z0-9][A-Z0-9-]{1,11}$")
    destination: str = Field(pattern=r"^[A-Z0-9][A-Z0-9-]{1,11}$")
    departure_date: date
    return_date: date | None = None
    adults: Literal[1] = 1
    cabin: Literal["ECONOMY"] = "ECONOMY"
    markets: list[str] = Field(min_length=1, max_length=10)
    baseline_market: str = Field(pattern=r"^[A-Z]{2}$")
    checked_baggage: Baggage = Field(default_factory=lambda: Baggage(pieces=1, weight_kg=23))
    data_mode: Literal["MOCK", "REAL"] = "MOCK"

    @field_validator("markets")
    @classmethod
    def valid_markets(cls, values):
        if len(set(values)) != len(values) or any(len(v) != 2 or not v.isalpha() or not v.isupper() for v in values):
            raise ValueError("Markets must be unique two-letter uppercase country codes")
        return values

    @model_validator(mode="after")
    def valid_search(self):
        if self.origin == self.destination:
            raise ValueError("Origin and destination must differ")
        if self.return_date and self.return_date < self.departure_date:
            raise ValueError("Return date must not precede departure date")
        if self.baseline_market not in self.markets:
            raise ValueError("Baseline market must be included in markets")
        return self


class Money(StrictModel):
    amount: Decimal = Field(gt=0, max_digits=16, decimal_places=6)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class Segment(StrictModel):
    origin: str
    destination: str
    departure_at: datetime
    arrival_at: datetime
    marketing_carrier: str
    operating_carrier: str
    flight_number: str

    @model_validator(mode="after")
    def aware_times(self):
        if self.departure_at.utcoffset() is None or self.arrival_at.utcoffset() is None:
            raise ValueError("Segment timestamps must include timezone offsets")
        if self.arrival_at <= self.departure_at:
            raise ValueError("Arrival must follow departure")
        return self


class FareConditions(StrictModel):
    cabin: Literal["ECONOMY"] = "ECONOMY"
    fare_product: str | None
    checked_baggage: Baggage | None
    cabin_baggage: Baggage | None
    refundable: bool | None
    changeable: bool | None
    change_penalty: Money | None = None
    refund_penalty: Money | None = None


class Offer(StrictModel):
    id: str
    segments: list[Segment] = Field(min_length=1)
    adults: Literal[1] = 1
    market: str
    total: Money
    conditions: FareConditions
    mandatory_fees_included: bool | None
    observed_at: datetime
    expires_at: datetime
    purchase_eligibility: Literal["UNKNOWN"] = "UNKNOWN"
    source: Literal["mock-flights-v1"] = "mock-flights-v1"
    data_mode: Literal["MOCK"] = "MOCK"


class ExcludedOffer(StrictModel):
    offer_id: str
    reason_codes: list[str]


class RankedOffer(StrictModel):
    offer_id: str
    total_eur: Decimal
    savings_eur: Decimal | None
    savings_percent: Decimal | None


class ComparisonGroup(StrictModel):
    id: str
    baseline_offer_id: str | None
    offers: list[RankedOffer]


class ObservedSegment(StrictModel):
    origin: str
    destination: str
    departure_local: str
    arrival_local: str
    airline: str | None = None
    flight_number: str | None = None
    duration_minutes: int | None = None


class PriceObservation(StrictModel):
    id: str
    source: Literal["serpapi-google-flights"] = "serpapi-google-flights"
    data_mode: Literal["REAL"] = "REAL"
    localization_country: str
    price: Money
    segments: list[ObservedSegment] = Field(min_length=1)
    total_duration_minutes: int | None = None
    retrieved_at: datetime
    provider_created_at: datetime | None = None
    provider_search_id: str
    source_url: str | None = None
    itinerary_complete: bool
    departure_token: str | None = None
    booking_token: str | None = None
    fare_conditions_verified: Literal[False] = False
    savings_eur: None = None
    notes: list[str] = Field(default_factory=list)


class SearchResult(StrictModel):
    search_id: UUID
    status: Literal["COMPLETED", "PARTIAL", "NO_RESULTS", "FAILED"]
    data_mode: Literal["MOCK", "REAL"] = "MOCK"
    criteria: SearchCriteria
    offers: list[Offer]
    comparison_groups: list[ComparisonGroup]
    excluded_offers: list[ExcludedOffer]
    warnings: list[str]
    observations: list[PriceObservation] = Field(default_factory=list)
    fx_snapshot_id: str | None = "mock-fx-v1"
    comparison_version: str = "1.0"
    created_at: datetime

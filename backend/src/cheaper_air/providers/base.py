from datetime import datetime
from typing import Protocol
from cheaper_air.domain.models import Offer, SearchCriteria


class FlightProvider(Protocol):
    async def search(self, criteria: SearchCriteria, now: datetime) -> list[Offer]: ...

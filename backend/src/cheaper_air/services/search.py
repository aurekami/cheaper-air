from datetime import datetime, timezone
from uuid import uuid4
from cheaper_air.domain.comparison import compare
from cheaper_air.domain.models import SearchCriteria, SearchResult
from cheaper_air.providers.mock_flights import MockFlightProvider
from cheaper_air.providers.mock_fx import MockFxProvider
from cheaper_air.services.airports import get_airport_catalog


class SearchService:
    def __init__(self, repository, provider=None, clock=None, real_provider=None):
        self.real_provider = real_provider
        self.repository = repository
        self.provider = provider or MockFlightProvider()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    async def search(self, criteria: SearchCriteria) -> SearchResult:
        catalog = get_airport_catalog()
        canonical = {}
        for field, code in (("origin", criteria.origin), ("destination", criteria.destination)):
            airport = catalog.get(code)
            if airport is None:
                raise ValueError(f"Unknown airport code: {code}. Select an airport from the global catalog.")
            canonical[field] = airport["code"]
            if airport['type'] == 'closed':
                raise ValueError(f"Airport {code} is marked closed in the reference catalog.")
        criteria = SearchCriteria.model_validate(criteria.model_dump() | canonical)
        now = self.clock()
        if criteria.departure_date < now.date():
            raise ValueError("Departure date must not be in the past")
        if criteria.data_mode == 'REAL':
            from cheaper_air.providers.errors import ProviderError
            if self.real_provider is None:
                raise ProviderError('SERPAPI_NOT_CONFIGURED', 'Configure SERPAPI_API_KEY to enable REAL search.')
            observations, provider_warnings, partial = await self.real_provider.search(criteria, now)
            warnings = ['REAL: SerpApi Google Flights observations; prices may be cached and are not guaranteed at booking.',
                        'Localization country is not verified point of sale. Fare conditions and checked baggage are unknown; confirmed savings are unavailable.',
                        *provider_warnings]
            if criteria.return_date:
                warnings.append('Return itinerary not selected. Round-trip prices are indicative for the outbound selection.')
            result = SearchResult(search_id=uuid4(), status='PARTIAL' if partial else 'COMPLETED' if observations else 'NO_RESULTS',
                data_mode='REAL', criteria=criteria, offers=[], comparison_groups=[], excluded_offers=[],
                observations=observations, warnings=warnings, fx_snapshot_id=None, created_at=now)
            self.repository.save(result)
            return result
        offers = await self.provider.search(criteria, now)
        groups, excluded = compare(offers, criteria, now, MockFxProvider())
        warnings = ["MOCK: synthetic flights, prices and FX rates; not bookable inventory.",
                    "Purchase eligibility in another market is unknown."]
        if (criteria.origin, criteria.destination) not in self.provider.supported_routes:
            warnings.append("UNSUPPORTED_MOCK_ROUTE: no synthetic scenario for this route. Available: VNO–LHR, VNO–MIA. This search explicitly selected MOCK. Use REAL mode for connected provider prices.")
        unsupported = sorted(set(criteria.markets) - self.provider.supported_markets)
        if unsupported:
            warnings.append("Unsupported MOCK markets: " + ", ".join(unsupported))
        if any(group.baseline_offer_id is None for group in groups):
            warnings.append("BASELINE_UNAVAILABLE: savings are null for groups without a baseline.")
        status = "NO_RESULTS" if not offers else "PARTIAL" if unsupported else "COMPLETED"
        result = SearchResult(search_id=uuid4(), status=status, criteria=criteria, offers=offers,
                              comparison_groups=groups, excluded_offers=excluded, warnings=warnings, created_at=now)
        self.repository.save(result)
        return result

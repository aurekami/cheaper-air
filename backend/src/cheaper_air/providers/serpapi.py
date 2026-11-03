"""Google Flights observations via SerpApi; never verified fare-equivalent offers."""
import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse
import httpx
from pydantic import ValidationError
from cheaper_air.domain.models import Money, ObservedSegment, PriceObservation, SearchCriteria
from cheaper_air.providers.errors import ProviderError


class SerpApiProvider:
    endpoint = 'https://serpapi.com/search.json'
    max_markets = 3

    def __init__(self, api_key=None, client=None):
        self.api_key, self.client = api_key, client

    async def search(self, criteria: SearchCriteria, now: datetime):
        if not self.api_key or not self.api_key.get_secret_value().strip():
            raise ProviderError('SERPAPI_NOT_CONFIGURED', 'REAL paieškai reikia SERPAPI_API_KEY lokaliame .env. Pridėkite raktą ir perkraukite backendą. MOCK režimas lieka atskiras.')
        if len(criteria.markets) > self.max_markets:
            raise ProviderError('SEARCH_LIMIT', 'REAL search supports at most 3 localization countries per request.', 422)
        if not all(re.fullmatch(r'[A-Z]{3}', code) for code in (criteria.origin, criteria.destination)):
            raise ProviderError('PROVIDER_AIRPORT_UNSUPPORTED', 'SerpApi flight search requires IATA airport codes. This directory airport has no supported IATA identifier.', 422)
        async with httpx.AsyncClient(timeout=45) as default_client:
            client = self.client or default_client
            outcomes = await asyncio.gather(*(self._market(client, criteria, market, now) for market in criteria.markets), return_exceptions=True)
        observations, warnings, successes = [], [], 0
        for market, outcome in zip(criteria.markets, outcomes):
            if isinstance(outcome, ProviderError):
                warnings.append(f'{market}: {outcome.code} — {outcome}')
            elif isinstance(outcome, Exception):
                raise ProviderError('PROVIDER_RESPONSE_INVALID', 'The flight data provider returned an unsupported response.')
            else:
                items, notes = outcome
                observations.extend(items); warnings.extend(notes); successes += 1
        if not successes:
            first = next(o for o in outcomes if isinstance(o, ProviderError))
            raise first
        # Stable numeric ordering is presentation only, never equivalence or savings.
        observations.sort(key=lambda o: (o.price.amount, o.id))
        return observations, warnings, successes < len(criteria.markets)

    async def _market(self, client, criteria, market, now):
        params = {'engine':'google_flights', 'api_key':self.api_key.get_secret_value(),
                  'departure_id':criteria.origin, 'arrival_id':criteria.destination,
                  'outbound_date':criteria.departure_date.isoformat(), 'type':1 if criteria.return_date else 2,
                  'adults':1, 'travel_class':1, 'currency':'EUR', 'hl':'en',
                  'gl':'uk' if market == 'GB' else market.lower()}
        if criteria.return_date:
            params['return_date'] = criteria.return_date.isoformat()
        try:
            response = await client.get(self.endpoint, params=params)
            response.raise_for_status()
        except httpx.TimeoutException:
            raise ProviderError('PROVIDER_TIMEOUT', 'Flight data request timed out. No substitute prices were generated.', 504) from None
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            code = 'PROVIDER_AUTH_FAILED' if status in (401,403) else 'PROVIDER_RATE_LIMIT' if status == 429 else 'PROVIDER_UNAVAILABLE'
            raise ProviderError(code, 'SerpApi request failed. Check the local API key, account quota and provider status.') from None
        except httpx.HTTPError:
            raise ProviderError('PROVIDER_UNAVAILABLE', 'Could not reach SerpApi. No substitute prices were generated.') from None
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError('Unexpected body')
            no_results = (data.get('error') == "Google Flights hasn't returned any results for this query."
                          and data.get('search_metadata', {}).get('status') == 'Success')
            if data.get('error') and not no_results:
                raise ProviderError('PROVIDER_SEARCH_FAILED', 'SerpApi could not complete this search. Check account access, quota and search dates.')
            metadata = data.get('search_metadata', {})
            if metadata.get('status') != 'Success' or not isinstance(metadata.get('id'),str):
                raise ValueError('Missing successful search metadata')
            if data.get('search_parameters',{}).get('currency') != 'EUR':
                raise ValueError('Unconfirmed response currency')
            entries = data.get('best_flights',[]) + data.get('other_flights',[])
            if not isinstance(entries,list):
                raise ValueError('Unexpected flight lists')
        except (ValueError, TypeError, AttributeError):
            raise ProviderError('PROVIDER_RESPONSE_INVALID', 'SerpApi returned incomplete or malformed flight data.') from None
        created = None
        try:
            created = datetime.strptime(metadata.get('created_at',''), '%Y-%m-%d %H:%M:%S UTC').replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            pass
        raw_url = metadata.get('google_flights_url')
        source_url = raw_url if isinstance(raw_url,str) and urlparse(raw_url).scheme == 'https' and urlparse(raw_url).hostname in ('www.google.com','google.com') else None
        items, skipped, seen = [], 0, set()
        for entry in entries[:100]:
            try:
                if not isinstance(entry,dict) or isinstance(entry.get('price'),bool):
                    raise ValueError('Missing price')
                price = Decimal(str(entry['price']))
                if not price.is_finite() or price <= 0:
                    raise ValueError('Invalid price')
                segments=[]
                for leg in entry['flights']:
                    departure, arrival = leg['departure_airport'], leg['arrival_airport']
                    # Times are local strings. Do not invent timezone offsets.
                    for airport in (departure, arrival):
                        datetime.strptime(airport['time'], '%Y-%m-%d %H:%M')
                        if not re.fullmatch(r'[A-Z]{3}',airport['id']):
                            raise ValueError('Invalid airport')
                    segments.append(ObservedSegment(origin=departure['id'],destination=arrival['id'],
                        departure_local=departure['time'],arrival_local=arrival['time'],airline=leg.get('airline'),
                        flight_number=leg.get('flight_number'),duration_minutes=leg.get('duration')))
                if not segments or segments[0].origin != criteria.origin or segments[-1].destination != criteria.destination:
                    raise ValueError('Wrong route')
                if segments[0].departure_local[:10] != criteria.departure_date.isoformat() or any(a.destination != b.origin for a,b in zip(segments,segments[1:])):
                    raise ValueError('Wrong date or broken connections')
                signature=json.dumps({'segments':[s.model_dump() for s in segments],'price':str(price)},sort_keys=True)
                key=hashlib.sha256(signature.encode()).hexdigest()[:16]
                if key in seen: continue
                seen.add(key)
                notes=['Localized search result; sales-market eligibility and fare conditions are not verified.',
                       'Checked baggage, change and refund conditions are unknown; no confirmed savings.']
                if criteria.return_date:
                    notes.append('Round-trip indicative total for this outbound selection. Return flights have not been selected; itinerary is incomplete.')
                items.append(PriceObservation(id=f'serpapi-{market.lower()}-{key}', localization_country=market,
                    price=Money(amount=price,currency='EUR'),segments=segments,total_duration_minutes=entry.get('total_duration'),
                    retrieved_at=now,provider_created_at=created,provider_search_id=metadata['id'],source_url=source_url,
                    itinerary_complete=criteria.return_date is None,notes=notes,
                    departure_token=entry.get("departure_token"),booking_token=entry.get("booking_token")))
            except (ValueError, TypeError, KeyError, InvalidOperation, ValidationError):
                skipped += 1
        warnings=[f'{market}: skipped {skipped} incomplete provider results.'] if skipped else []
        if entries and not items:
            raise ProviderError('PROVIDER_RESPONSE_INVALID', 'Provider results did not contain usable prices and matching flight segments.')
        return items,warnings

    async def booking_stage(self, criteria, market, token_name, token):
        if not self.api_key or not self.api_key.get_secret_value().strip():
            raise ProviderError('SERPAPI_NOT_CONFIGURED','Configure SERPAPI_API_KEY before checking sellers.')
        if token_name not in ('departure_token','booking_token') or not token:
            raise ProviderError('BOOKING_TOKEN_MISSING','Refresh this search to obtain a current flight selection.',409)
        params={'engine':'google_flights','api_key':self.api_key.get_secret_value(),
                'departure_id':criteria.origin,'arrival_id':criteria.destination,
                'outbound_date':criteria.departure_date.isoformat(),'type':1 if criteria.return_date else 2,
                'adults':1,'travel_class':1,'currency':'EUR','hl':'en',
                'gl':'uk' if market=='GB' else market.lower(),token_name:token,'no_cache':'true'}
        if criteria.return_date: params['return_date']=criteria.return_date.isoformat()
        async with httpx.AsyncClient(timeout=45) as default_client:
            try:
                response=await (self.client or default_client).get(self.endpoint,params=params)
                response.raise_for_status()
                body=response.json()
                if not isinstance(body,dict) or body.get('error') or body.get('search_metadata',{}).get('status')!='Success':
                    raise ProviderError('BOOKING_UNAVAILABLE','Current seller options could not be retrieved. The selection may have expired.',409)
                if body.get('search_parameters',{}).get('currency')!='EUR':
                    raise ProviderError('BOOKING_CURRENCY_UNKNOWN','Seller response currency could not be verified.',502)
                return body
            except httpx.TimeoutException:
                raise ProviderError('PROVIDER_TIMEOUT','Checking seller prices timed out.',504) from None
            except httpx.HTTPError:
                raise ProviderError('BOOKING_UNAVAILABLE','Could not check current seller offers. Check API access and quota.',503) from None
            except ValueError:
                raise ProviderError('PROVIDER_RESPONSE_INVALID','Invalid seller response.',502) from None

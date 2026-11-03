"""Resolve complete itineraries and quoted seller links; never purchase tickets."""
import ipaddress
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
import re
from urllib.parse import urlparse, urljoin
from uuid import uuid4
import httpx
from pydantic import ValidationError
from cheaper_air.domain.models import Money, ObservedSegment
from cheaper_air.providers.errors import ProviderError


def safe_url(value, google_action=False):
    if not isinstance(value,str): return False
    try:
        parsed=urlparse(value)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None,443): return False
        host=parsed.hostname.lower()
        if host=='localhost' or '.' not in host or host.endswith(('.local','.localhost','.internal')): return False
        try:
            ipaddress.ip_address(host)
            return False
        except ValueError: pass
        if google_action:
            return host in ('google.com','www.google.com') and parsed.path.startswith('/travel/clk')
        return True
    except ValueError: return False


def segments(entry):
    result=[]
    for flight in entry['flights']:
        departure,arrival=flight['departure_airport'],flight['arrival_airport']
        for airport in (departure,arrival):
            datetime.strptime(airport['time'],'%Y-%m-%d %H:%M')
        result.append(ObservedSegment(origin=departure['id'],destination=arrival['id'],departure_local=departure['time'],
            arrival_local=arrival['time'],airline=flight.get('airline'),flight_number=flight.get('flight_number'),duration_minutes=flight.get('duration')))
    if not result or any(a.destination!=b.origin for a,b in zip(result,result[1:])):
        raise ValueError('Broken itinerary')
    return result


def signature(items):
    return [(s.origin,s.destination,s.departure_local,s.arrival_local,(s.flight_number or '').replace(' ','')) for s in items]


class BookingRefreshParser(HTMLParser):
    """Accept a standard HTML redirect, without executing provider JavaScript."""
    def __init__(self):
        super().__init__()
        self.target=None

    def handle_starttag(self,tag,attrs):
        values=dict(attrs)
        if tag.lower()=='meta' and values.get('http-equiv','').lower()=='refresh':
            match=re.match(r"^\s*\d+(?:\.\d+)?\s*;\s*url\s*=\s*(.+)$",values.get('content',''),re.I)
            if match: self.target=match.group(1).strip().strip("\"'")


class BookingService:
    def __init__(self,repository,provider,clock=None,redirect_client=None):
        self.repository,self.provider=repository,provider
        self.clock=clock or (lambda:datetime.now(timezone.utc))
        self.redirect_client=redirect_client

    async def options(self,search_id,observation_id):
        result=self.repository.get(str(search_id))
        if result is None: raise ProviderError('SEARCH_NOT_FOUND','Search not found.',404)
        observation=next((o for o in result.observations if o.id==observation_id),None)
        if result.data_mode!='REAL' or observation is None:
            raise ProviderError('OBSERVATION_NOT_FOUND','Only a real source observation can be checked for sellers.',404)
        original_price=observation.price.amount
        criteria=result.criteria
        # Older snapshots lack tokens. Re-fetch only this country, matching the actual flights.
        if not observation.booking_token and not observation.departure_token:
            query=criteria.model_copy(update={'markets':[observation.localization_country],'baseline_market':observation.localization_country})
            fresh,_,_=await self.provider.search(query,self.clock())
            observation=next((o for o in fresh if signature(o.segments)==signature(observation.segments)),None)
            if observation is None:
                raise ProviderError('OFFER_CHANGED','This flight no longer appears in results. Run a new search.',409)
        outbound=observation.segments
        returning=[]
        token=observation.booking_token
        if criteria.return_date:
            if not observation.departure_token:
                raise ProviderError('BOOKING_TOKEN_MISSING','No outbound selection token. Run a new search.',409)
            body=await self.provider.booking_stage(criteria,observation.localization_country,'departure_token',observation.departure_token)
            candidates=[]
            for entry in body.get('best_flights',[])+body.get('other_flights',[]):
                try:
                    legs=segments(entry)
                    price=Money(amount=entry['price'],currency='EUR')
                    if legs[0].origin!=criteria.destination or legs[-1].destination!=criteria.origin or legs[0].departure_local[:10]!=criteria.return_date.isoformat() or not entry.get('booking_token'):
                        continue
                    candidates.append((price.amount,entry['booking_token'],legs))
                except (KeyError,TypeError,ValueError,ValidationError): continue
            if not candidates:
                raise ProviderError('RETURN_UNAVAILABLE','No matching return selection with a booking token was found. Change dates or search again.',409)
            _,token,returning=min(candidates,key=lambda value:value[0])
        if not token:
            raise ProviderError('BOOKING_TOKEN_MISSING','No seller token is available. Run a new search.',409)
        body=await self.provider.booking_stage(criteria,observation.localization_country,'booking_token',token)
        # Confirm the response still describes the selected complete itinerary.
        try:
            selected=[segments(entry) for entry in body['selected_flights']]
            if not selected or signature(selected[0])!=signature(outbound): raise ValueError('Outbound changed')
            if criteria.return_date and (len(selected)!=2 or signature(selected[1])!=signature(returning)): raise ValueError('Return changed')
            if not criteria.return_date and len(selected)!=1: raise ValueError('Unexpected extra legs')
        except (KeyError,TypeError,ValueError,ValidationError):
            raise ProviderError('ITINERARY_UNVERIFIED','Seller response did not confirm the selected itinerary. No purchase link is presented.',409) from None
        now=self.clock()
        offers=[]
        for option in body.get('booking_options',[]):
            if not isinstance(option,dict) or option.get('separate_tickets'): continue
            together=option.get('together',{})
            action=together.get('booking_request',{})
            try:
                money=Money(amount=together['price'],currency='EUR') if together.get('price') is not None else None
                seller=together['book_with']
                url=action['url']
                post_data=action.get('post_data')
                if not isinstance(seller,str) or not seller.strip() or not safe_url(url,google_action=post_data is not None): continue
                if post_data is not None and (not isinstance(post_data,str) or len(post_data)>200000): continue
                offers.append({'seller':seller,'price':money.model_dump(mode='json') if money else None,'seller_price_provided':money is not None,'airline':together.get('airline') is True,
                    'baggage_policy':together.get('baggage_prices',[]),'url':url,'post_data':post_data,
                    'price_change_eur':str(money.amount-original_price) if money else None})
            except (KeyError,TypeError,ValueError,ValidationError,InvalidOperation): continue
        offers.sort(key=lambda item:(item['price'] is None,Decimal(item['price']['amount']) if item['price'] else Decimal('Infinity')))
        quote_id=str(uuid4())
        payload={'quote_id':quote_id,'search_id':str(search_id),'observation_id':observation_id,
            'checked_at':now.isoformat(),'link_expires_at':(now+timedelta(minutes=20)).isoformat(),
            'outbound':[s.model_dump(mode='json') for s in outbound],'returning':[s.model_dump(mode='json') for s in returning],
            'options':offers,'provider_search_id':body.get('search_metadata',{}).get('id'),
            'warnings':['Seller-quoted prices can change before checkout. No ticket has been reserved.',
                'Checked-bag weight and fare conditions are not verified. Read seller baggage terms.',
                'Cheapest returned matching return was selected for this outbound; this is not an exhaustive cheapest-trip search.']}
        self.repository.save_quote(quote_id,payload)
        public={**payload,'options':[{k:v for k,v in item.items() if k not in ('url','post_data')} | {'purchase_url':f'/api/v1/booking-links/{quote_id}/{i}'} for i,item in enumerate(offers)]}
        public['status']='SELLERS_FOUND' if offers else 'NO_PURCHASE_LINKS'
        return public

    async def purchase_url(self,quote_id,index):
        quote=self.repository.get_quote(str(quote_id))
        if quote is None or index<0 or index>=len(quote['options']):
            raise ProviderError('BOOKING_LINK_NOT_FOUND','Seller link not found.',404)
        if self.clock()>=datetime.fromisoformat(quote['link_expires_at']):
            raise ProviderError('BOOKING_LINK_EXPIRED','Check seller prices again to refresh this link.',410)
        option=quote['options'][index]
        if option['post_data'] is None:
            if not safe_url(option['url']): raise ProviderError('UNSAFE_BOOKING_LINK','Invalid seller link.',502)
            return option['url']
        if not safe_url(option['url'],google_action=True):
            raise ProviderError('UNSAFE_BOOKING_LINK','Invalid booking action.',502)
        # Resolve the provider's POST action exactly as specified. Do not visit the seller server-side.
        async with httpx.AsyncClient(timeout=20,follow_redirects=False) as default_client:
            try:
                response=await (self.redirect_client or default_client).post(option['url'],content=option['post_data'],headers={'Content-Type':'application/x-www-form-urlencoded'},follow_redirects=False)
                target=response.headers.get('location') if response.status_code in (301,302,303,307,308) else None
                if response.status_code==200 and len(response.content)<=100000 and 'text/html' in response.headers.get('content-type',''):
                    parser=BookingRefreshParser()
                    parser.feed(response.text)
                    target=parser.target
                location=urljoin(option['url'],target or '')
                if not target or not safe_url(location):
                    raise ProviderError('BOOKING_REDIRECT_UNAVAILABLE','The seller redirect could not be resolved. Check seller prices again.',409)
                return location
            except httpx.HTTPError:
                raise ProviderError('BOOKING_REDIRECT_UNAVAILABLE','Could not open the seller. Check seller prices again.',503) from None

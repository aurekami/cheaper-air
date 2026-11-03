from datetime import datetime, timezone, timedelta
from decimal import Decimal
import httpx
import pytest
from cheaper_air.domain.models import SearchCriteria, SearchResult, PriceObservation, Money, ObservedSegment
from cheaper_air.persistence.repositories import SearchRepository
from cheaper_air.providers.errors import ProviderError
from cheaper_air.services.booking import BookingService, safe_url
from uuid import uuid4

NOW=datetime(2026,11,3,12,tzinfo=timezone.utc)


def raw(origin,destination,date,number='ZZ 1'):
    return {'flights':[{'departure_airport':{'id':origin,'time':date+' 10:00'},'arrival_airport':{'id':destination,'time':date+' 13:00'},'flight_number':number,'airline':'TEST ONLY','duration':180}]}


def setup(tmp_path,roundtrip=True,tokens=True):
    repo=SearchRepository('sqlite:///'+str(tmp_path/'booking.db'));repo.initialize()
    criteria=SearchCriteria(origin='VNO',destination='MIA',departure_date='2099-02-12',return_date='2099-02-20' if roundtrip else None,markets=['US'],baseline_market='US',data_mode='REAL')
    leg=ObservedSegment(origin='VNO',destination='MIA',departure_local='2099-02-12 10:00',arrival_local='2099-02-12 13:00',flight_number='ZZ 1',airline='TEST ONLY',duration_minutes=180)
    obs=PriceObservation(id='test-observation',localization_country='US',price=Money(amount='100',currency='EUR'),segments=[leg],retrieved_at=NOW,provider_search_id='test-source',itinerary_complete=not roundtrip,departure_token='outbound-token' if tokens and roundtrip else None,booking_token='booking-token' if tokens and not roundtrip else None)
    result=SearchResult(search_id=uuid4(),status='COMPLETED',data_mode='REAL',criteria=criteria,offers=[],comparison_groups=[],excluded_offers=[],warnings=[],observations=[obs],created_at=NOW,fx_snapshot_id=None)
    repo.save(result)
    return repo,result


class FakeProvider:
    def __init__(self,roundtrip=True): self.calls=[];self.roundtrip=roundtrip;self.wrong=False;self.no_links=False
    async def booking_stage(self,criteria,market,name,token):
        self.calls.append((name,token))
        if name=='departure_token':
            return {'best_flights':[raw('MIA','VNO','2099-02-20','ZZ 2') | {'price':120,'booking_token':'expensive'},raw('MIA','VNO','2099-02-20','ZZ 3') | {'price':100,'booking_token':'cheapest'},raw('MIA','LHR','2099-02-20') | {'price':10,'booking_token':'wrong-route'}]}
        selected=[raw('VNO','LHR' if self.wrong else 'MIA','2099-02-12')]
        if self.roundtrip:selected.append(raw('MIA','VNO','2099-02-20','ZZ 3'))
        return {'selected_flights':selected,'search_metadata':{'id':'test-quote'},'booking_options':[] if self.no_links else [
            {'together':{'book_with':'More expensive','price':110,'booking_request':{'url':'https://airline.example/checkout?id=1'}}},
            {'together':{'book_with':'Cheapest seller','price':105,'baggage_prices':['No checked bags'],'booking_request':{'url':'https://www.google.com/travel/clk/f','post_data':'x=a%2Bb&y=1+2'}}},
            {'separate_tickets':True,'together':{'book_with':'Separate','price':1,'booking_request':{'url':'https://airline.example/checkout'}}},
            {'together':{'book_with':'Phone only','price':2}},
            {'together':{'book_with':'Unsafe','price':3,'booking_request':{'url':'http://localhost'}}}]}


async def test_round_trip_sellers_and_changed_price(tmp_path):
    repo,result=setup(tmp_path);provider=FakeProvider()
    quote=await BookingService(repo,provider,clock=lambda:NOW).options(result.search_id,'test-observation')
    assert provider.calls==[('departure_token','outbound-token'),('booking_token','cheapest')]
    assert quote['returning'][0]['flight_number']=='ZZ 3'
    assert len(quote['options'])==2
    assert quote['options'][0]['seller']=='Cheapest seller'
    assert quote['options'][0]['price_change_eur']=='5'
    assert 'url' not in quote['options'][0] and 'post_data' not in quote['options'][0]
    assert quote['options'][0]['purchase_url'].startswith('/api/v1/booking-links/')


async def test_one_way_and_no_links(tmp_path):
    repo,result=setup(tmp_path,roundtrip=False);provider=FakeProvider(False)
    quote=await BookingService(repo,provider,clock=lambda:NOW).options(result.search_id,'test-observation')
    assert provider.calls==[('booking_token','booking-token')]
    assert quote['returning']==[]
    provider.no_links=True
    quote=await BookingService(repo,provider,clock=lambda:NOW).options(result.search_id,'test-observation')
    assert quote['status']=='NO_PURCHASE_LINKS' and quote['options']==[]


async def test_changed_itinerary_gets_no_buy_button(tmp_path):
    repo,result=setup(tmp_path);provider=FakeProvider();provider.wrong=True
    with pytest.raises(ProviderError) as error:
        await BookingService(repo,provider,clock=lambda:NOW).options(result.search_id,'test-observation')
    assert error.value.code=='ITINERARY_UNVERIFIED'


async def test_exact_post_redirect_and_expiry(tmp_path):
    repo,result=setup(tmp_path);provider=FakeProvider()
    quote=await BookingService(repo,provider,clock=lambda:NOW).options(result.search_id,'test-observation')
    def handler(request):
        assert request.url.host=='www.google.com'
        assert request.method=='POST'
        assert request.content==b'x=a%2Bb&y=1+2'
        return httpx.Response(302,headers={'Location':'https://airline.example/checkout?flight=1'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service=BookingService(repo,provider,clock=lambda:NOW,redirect_client=client)
        assert await service.purchase_url(quote['quote_id'],0)=='https://airline.example/checkout?flight=1'
        assert await service.purchase_url(quote['quote_id'],1)=='https://airline.example/checkout?id=1'
        with pytest.raises(ProviderError) as error:
            await BookingService(repo,provider,clock=lambda:NOW+timedelta(minutes=21)).purchase_url(quote['quote_id'],0)
        assert error.value.status==410


@pytest.mark.parametrize('url',['http://seller.example','https://localhost/x','https://127.0.0.1/x','https://user:pass@seller.example/x','javascript:alert(1)','https://[::1]/'])
def test_unsafe_links(url):
    assert not safe_url(url)


def test_google_post_action_allowlist():
    assert safe_url('https://www.google.com/travel/clk/f',True)
    assert not safe_url('https://www.google.com.evil.example/travel/clk/f',True)
    assert not safe_url('https://www.google.com/unrelated',True)


async def test_seller_link_without_price_is_not_advertised_as_confirmed_price(tmp_path):
    repo,result=setup(tmp_path,roundtrip=False)
    class MissingPrice(FakeProvider):
        async def booking_stage(self,*args):
            body=await super().booking_stage(*args)
            body['booking_options']=[{'together':{'book_with':'American','booking_request':{'url':'https://www.google.com/travel/clk/f','post_data':'x=1'}}}]
            return body
    quote=await BookingService(repo,MissingPrice(False),clock=lambda:NOW).options(result.search_id,'test-observation')
    assert quote['options'][0]['price'] is None
    assert quote['options'][0]['price_change_eur'] is None
    assert quote['options'][0]['seller_price_provided'] is False
    assert quote['options'][0]['purchase_url']


async def test_google_html_meta_refresh_handoff(tmp_path):
    repo,result=setup(tmp_path)
    provider=FakeProvider()
    quote=await BookingService(repo,provider,clock=lambda:NOW).options(result.search_id,'test-observation')
    def handler(request):
        assert request.content==b'x=a%2Bb&y=1+2'
        return httpx.Response(200,headers={'content-type':'text/html'},text='<html><head><meta http-equiv="refresh" content="0;URL=https://airline.example/checkout?a=1&amp;b=2"></head></html>')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await BookingService(repo,provider,clock=lambda:NOW,redirect_client=client).purchase_url(quote['quote_id'],0)=='https://airline.example/checkout?a=1&b=2'


async def test_missing_or_private_redirect_is_not_followed(tmp_path):
    repo,result=setup(tmp_path);provider=FakeProvider()
    quote=await BookingService(repo,provider,clock=lambda:NOW).options(result.search_id,'test-observation')
    for html in ('<html>unavailable</html>','<meta http-equiv="refresh" content="0;URL=https://127.0.0.1/private">'):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,headers={'content-type':'text/html'},text=html))) as client:
            with pytest.raises(ProviderError):
                await BookingService(repo,provider,clock=lambda:NOW,redirect_client=client).purchase_url(quote['quote_id'],0)


def test_booking_http_routes(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from cheaper_air.config import Settings
    import cheaper_air.main as main
    repo,result=setup(tmp_path)
    monkeypatch.setattr(main,'SerpApiProvider',lambda *args:FakeProvider())
    with TestClient(main.create_app(settings=Settings(serpapi_api_key=None),repository=repo)) as client:
        response=client.post(f'/api/v1/searches/{result.search_id}/observations/test-observation/booking-options')
        assert response.status_code==200
        quote=response.json()
        assert quote['options'][0]['seller']=='Cheapest seller'
        assert 'post_data' not in response.text
        # Direct seller URLs are handed to the browser, never fetched by the server.
        link=client.get(quote['options'][1]['purchase_url'],follow_redirects=False)
        assert link.status_code==303
        assert link.headers['location']=='https://airline.example/checkout?id=1'
        assert client.get(f"/api/v1/booking-links/{quote['quote_id']}/-1").status_code==404
        assert client.post(f'/api/v1/searches/{result.search_id}/observations/unknown/booking-options').status_code==404

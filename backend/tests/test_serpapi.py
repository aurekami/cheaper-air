import json
from datetime import datetime, timezone
from decimal import Decimal
import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from cheaper_air.config import Settings
from cheaper_air.domain.models import SearchCriteria
from cheaper_air.main import create_app
from cheaper_air.persistence.repositories import SearchRepository
from cheaper_air.providers.errors import ProviderError
from cheaper_air.providers.serpapi import SerpApiProvider
from cheaper_air.services.airports import get_airport_catalog

NOW = datetime(2026,11,3,12,tzinfo=timezone.utc)


def criteria(destination='WAW', **updates):
    return SearchCriteria.model_validate(dict(origin='VNO',destination=destination,departure_date='2099-02-12',markets=['LT','GB','US'],baseline_market='LT',data_mode='REAL') | updates)


def response_body(destination='WAW', price=123, **updates):
    return {'search_metadata':{'status':'Success','id':'test-source-id','created_at':'2026-11-03 11:55:00 UTC','google_flights_url':'https://www.google.com/travel/flights'},
            'search_parameters':{'currency':'EUR'}, 'best_flights':[{'price':price,'total_duration':90,
            'flights':[{'departure_airport':{'id':'VNO','time':'2099-02-12 10:00'},
                        'arrival_airport':{'id':destination,'time':'2099-02-12 11:30'},'flight_number':'ZZ 12','airline':'TEST FIXTURE AIRLINE','duration':90}]}]} | updates


async def test_global_routes_and_localization_are_not_mock_offers():
    calls=[]
    def handler(request):
        calls.append(request)
        assert request.url.params['currency']=='EUR'
        assert request.url.params['api_key']=='test-secret'
        assert 'bags' not in request.url.params  # carry-on count must not become checked-bag allowance
        return httpx.Response(200,json=response_body(request.url.params['arrival_id']))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider=SerpApiProvider(SecretStr('test-secret'),client)
        for destination in ('WAW','HND','NRT','SYD'):
            items,warnings,partial=await provider.search(criteria(destination),NOW)
            assert len(items)==3 and not partial
            assert all(item.data_mode=='REAL' and item.price.amount==Decimal('123') for item in items)
            assert all(item.savings_eur is None and not item.fare_conditions_verified for item in items)
            assert all(item.segments[0].destination==destination for item in items)
    assert {call.url.params['gl'] for call in calls} == {'lt','uk','us'}


async def test_missing_key_never_calls_network():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:pytest.fail('Unexpected network call'))) as client:
        with pytest.raises(ProviderError,match='SERPAPI_API_KEY'):
            await SerpApiProvider(None,client).search(criteria(),NOW)


@pytest.mark.parametrize('body', [[], {'search_metadata':{'status':'Success','id':'x'}}, response_body(price=-1), response_body(price=True), response_body('LHR'), response_body() | {'search_parameters':{'currency':'USD'}}])
async def test_malformed_or_wrong_route_results_are_rejected(body):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=body))) as client:
        with pytest.raises(ProviderError):
            await SerpApiProvider(SecretStr('test-secret'),client).search(criteria(),NOW)


async def test_rate_limit_and_partial_market_results():
    def handler(request):
        return httpx.Response(429) if request.url.params['gl']=='uk' else httpx.Response(200,json=response_body())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        items,warnings,partial=await SerpApiProvider(SecretStr('test-secret'),client).search(criteria(),NOW)
    assert len(items)==2 and partial
    assert any('GB: PROVIDER_RATE_LIMIT' in warning for warning in warnings)
    assert 'test-secret' not in ' '.join(warnings)


async def test_empty_search_and_incomplete_round_trip():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=response_body(best_flights=[])))) as client:
        assert (await SerpApiProvider(SecretStr('test-secret'),client).search(criteria(),NOW))[0]==[]
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=response_body()))) as client:
        items,_,_=await SerpApiProvider(SecretStr('test-secret'),client).search(criteria(return_date='2099-02-20'),NOW)
        assert all(not item.itinerary_complete for item in items)
        assert all(any('Return flights' in note for note in item.notes) for item in items)


async def test_real_api_history_and_no_mock_fx(tmp_path):
    repository=SearchRepository('sqlite:///'+str(tmp_path/'real.db'))
    settings=Settings(serpapi_api_key='test-secret')
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=response_body()))) as upstream:
        with TestClient(create_app(settings=settings,repository=repository,flight_client=upstream)) as client:
            response=client.post('/api/v1/searches',json=criteria().model_dump(mode='json'))
            assert response.status_code==200
            data=response.json()
            assert data['data_mode']=='REAL' and data['offers']==[] and data['comparison_groups']==[]
            assert data['fx_snapshot_id'] is None and len(data['observations'])==3
            assert client.get('/api/v1/searches/'+data['search_id']).json()==data
            assert 'test-secret' not in json.dumps(data)
            assert client.get('/api/v1/capabilities').json()['real']['configured'] is True


def test_missing_key_http_error(tmp_path):
    repository=SearchRepository('sqlite:///'+str(tmp_path/'missing.db'))
    with TestClient(create_app(settings=Settings(serpapi_api_key=None),repository=repository)) as client:
        response=client.post('/api/v1/searches',json=criteria().model_dump(mode='json'))
        assert response.status_code==503
        assert response.json()['error']['code']=='SERPAPI_NOT_CONFIGURED'
        assert client.get('/api/v1/searches').json()['items']==[]


def test_lithuanian_city_searches():
    catalog=get_airport_catalog()
    for query,country in [('varsuva','PL'),('Varšuvą','PL'),('tokijas','JP'),('Tokijų','JP')]:
        assert catalog.search(query)[0]['country']==country
    assert {'WAW','WMI'} <= {a['code'] for a in catalog.search('varsuva')}
    assert {'HND','NRT'} <= {a['code'] for a in catalog.search('tokijas')}
    assert catalog.get('WAW')['country']=='PL'
    assert catalog.get('HND')['country']=='JP'
    assert catalog.get('NRT')['country']=='JP'


async def test_request_limits_and_timeout():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:pytest.fail('Limit must prevent requests'))) as client:
        provider=SerpApiProvider(SecretStr('test-secret'),client)
        with pytest.raises(ProviderError) as error:
            await provider.search(criteria(markets=['LT','GB','US','DE']),NOW)
        assert error.value.code=='SEARCH_LIMIT'
        with pytest.raises(ProviderError) as error:
            await provider.search(criteria('EGLL'),NOW)
        assert error.value.code=='PROVIDER_AIRPORT_UNSUPPORTED'
    def timeout(request):
        raise httpx.ReadTimeout('secret test-secret URL must never be exposed',request=request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
        with pytest.raises(ProviderError) as error:
            await SerpApiProvider(SecretStr('test-secret'),client).search(criteria(),NOW)
        assert error.value.code=='PROVIDER_TIMEOUT'
        assert 'test-secret' not in str(error.value)


async def test_agent_cannot_change_explicit_real_mode(tmp_path):
    from cheaper_air.agent.orchestrator import Agent, AgentMessage
    from cheaper_air.services.search import SearchService
    repository=SearchRepository('sqlite:///'+str(tmp_path/'mode.db'))
    repository.initialize()
    body=criteria().model_dump(mode='json') | {'data_mode':'MOCK'}
    handler=lambda r:httpx.Response(200,json={'message':{'tool_calls':[{'function':{'name':'search_flights','arguments':body}}]}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as model:
        with pytest.raises(ProviderError) as error:
            await Agent(Settings(),SearchService(repository),model).run(AgentMessage(message='Warsaw',criteria_context={'data_mode':'REAL'}))
    assert error.value.code=='SERPAPI_NOT_CONFIGURED'
    assert repository.list(10,None)['items']==[]


async def test_google_no_results_message_is_not_provider_failure():
    body=response_body(best_flights=[]) | {'error': "Google Flights hasn't returned any results for this query."}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=body))) as client:
        items,warnings,partial=await SerpApiProvider(SecretStr('test-secret'),client).search(criteria(),NOW)
    assert items==[] and not partial

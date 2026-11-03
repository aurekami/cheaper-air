import json
from decimal import Decimal
import httpx
import pytest
from fastapi.testclient import TestClient
from cheaper_air.agent.orchestrator import Agent, AgentMessage
from cheaper_air.config import Settings
from cheaper_air.main import create_app
from cheaper_air.persistence.repositories import SearchRepository
from cheaper_air.services.airports import get_airport_catalog
from cheaper_air.services.search import SearchService


@pytest.mark.parametrize('code', ['VNO','MIA','JFK','HND','SYD','JNB','GRU','DXB'])
def test_airports_across_continents(code):
    airport = get_airport_catalog().get(code)
    assert airport and airport['code'] == code
    assert airport['country'] and airport['name']


def test_reference_search_and_non_iata_airports():
    catalog = get_airport_catalog()
    assert catalog.metadata['records'] == len(catalog.airports)
    assert len(catalog.airports) > 80000
    assert catalog.search('majami')[0]['code'] == 'MIA'
    assert catalog.search('sao paulo')[0]['country'] == 'BR'
    assert catalog.search('EGLL')[0]['code'] == 'LHR'
    assert catalog.search('Tokyo')[0]['country'] == 'JP'
    local = next(a for a in catalog.airports if not a['iata_code'] and a['type'] == 'small_airport')
    assert catalog.get(local['ident'])['ident'] == local['ident']
    assert catalog.search(local['ident'])[0]['ident'] == local['ident']
    assert catalog.search('not-a-real-airport-12345') == []


def test_global_airport_api_and_no_fabricated_prices(tmp_path):
    repository = SearchRepository('sqlite:///' + str(tmp_path / 'airports.db'))
    with TestClient(create_app(repository=repository)) as client:
        reply = client.get('/api/v1/airports', params={'q':'Singapore'}).json()
        assert reply['data_mode'] == 'REFERENCE'
        assert reply['items'][0]['code'] == 'SIN'
        assert client.get('/api/v1/airports/EGLL').json()['code'] == 'LHR'
        assert client.get('/api/v1/airports/NOTREAL').status_code == 404
        assert client.get('/api/v1/airports?limit=31').status_code == 422
        body = {'origin':'VNO','destination':'HND','departure_date':'2099-02-12','markets':['LT','GB','US'],'baseline_market':'LT'}
        result = client.post('/api/v1/searches',json=body).json()
        assert result['status'] == 'NO_RESULTS'
        assert result['criteria']['destination'] == 'HND'
        assert result['offers'] == []
        canonical = client.post('/api/v1/searches', json=body | {'destination':'EGLL'}).json()
        assert canonical['criteria']['destination'] == 'LHR'
        assert canonical['offers']
        invalid = client.post('/api/v1/searches',json=body | {'destination':'NOTREAL'})
        assert invalid.status_code == 422
        local = next(a for a in get_airport_catalog().airports if not a['iata_code'] and a['type']=='small_airport')
        assert client.post('/api/v1/searches',json=body | {'destination':local['ident']}).status_code == 200


async def test_agent_resolves_global_city_before_search(tmp_path):
    repository = SearchRepository('sqlite:///' + str(tmp_path / 'agent.db'))
    repository.initialize()
    context = {'origin':'VNO','destination':'LHR','departure_date':'2099-02-12','markets':['LT','GB','US'],'baseline_market':'LT'}
    calls = []
    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        if len(calls) == 1:
            function = {'name':'resolve_airport','arguments':{'query':'Tokyo Haneda'}}
        else:
            tool_message = next(m for m in payload['messages'] if m['role']=='tool')
            assert json.loads(tool_message['content'])['airports'][0]['code'] == 'HND'
            function = {'name':'search_flights','arguments':context | {'destination':'HND'}}
        return httpx.Response(200,json={'message':{'tool_calls':[{'function':function}]}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as model:
        result = await Agent(Settings(),SearchService(repository),model).run(AgentMessage(message='Tokyo Haneda',criteria_context=context))
    assert result['interpreted_criteria']['destination'] == 'HND'
    assert repository.get(result['search_id']).offers == []
    assert len(calls) == 2

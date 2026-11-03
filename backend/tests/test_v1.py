from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
import httpx
import pytest
from fastapi.testclient import TestClient
from cheaper_air.config import Settings
from cheaper_air.domain.comparison import compare
from cheaper_air.domain.models import Money, SearchCriteria
from cheaper_air.main import create_app
from cheaper_air.persistence.repositories import SearchRepository
from cheaper_air.providers.mock_flights import MockFlightProvider
from cheaper_air.providers.mock_fx import MockFxProvider

NOW = datetime(2027, 1, 1, tzinfo=timezone.utc)


def criteria(**updates):
    return SearchCriteria.model_validate(dict(origin="VNO", destination="LHR", departure_date="2099-02-12",
        markets=["LT", "GB", "US"], baseline_market="LT", **updates))


@pytest.fixture
async def offers():
    return await MockFlightProvider().search(criteria(), NOW)


def test_fx_rounding():
    fx = MockFxProvider()
    assert fx.convert(Money(amount="1.005", currency="EUR")) == Decimal("1.01")
    assert fx.convert(Money(amount="180", currency="GBP")) == Decimal("210.60")
    with pytest.raises(KeyError):
        fx.convert(Money(amount="1", currency="JPY"))


async def test_comparison_and_baggage(offers):
    groups, excluded = compare(offers, criteria(), NOW, MockFxProvider())
    assert len(groups) == 1
    best = groups[0].offers[0]
    assert best.offer_id == "mock-gb-standard"
    assert best.savings_eur == Decimal("29.40")
    assert best.savings_percent == Decimal("12.25")
    assert excluded[0].reason_codes == ["INSUFFICIENT_BAGGAGE"]


@pytest.mark.parametrize("mutation,reason", [
    ({"expires_at": NOW}, "INVALID_OFFER_TIME"),
    ({"mandatory_fees_included": None}, "UNKNOWN_MANDATORY_FEES"),
    ({"total": Money(amount="100", currency="JPY")}, "MISSING_FX_RATE"),
])
async def test_exclusions(offers, mutation, reason):
    changed = offers[0].model_copy(update=mutation)
    groups, excluded = compare([changed], criteria(), NOW, MockFxProvider())
    assert not groups
    assert reason in excluded[0].reason_codes


async def test_conditions_and_baseline(offers):
    changed = offers[1].model_copy(update={"conditions": offers[1].conditions.model_copy(update={"fare_product": "OTHER"})})
    groups, _ = compare([offers[0], changed], criteria(), NOW, MockFxProvider())
    assert len(groups) == 2
    missing = next(g for g in groups if g.baseline_offer_id is None)
    assert missing.offers[0].savings_eur is None
    unknown = changed.model_copy(update={"conditions": changed.conditions.model_copy(update={"refundable": None})})
    assert compare([unknown], criteria(), NOW, MockFxProvider())[1][0].reason_codes == ["UNKNOWN_FARE_CONDITIONS"]


async def test_wrong_itinerary(offers):
    segment = offers[0].segments[0].model_copy(update={"flight_number": "999"})
    other = offers[0].model_copy(update={"id": "other", "segments": [segment]})
    assert len(compare([offers[0], other], criteria(), NOW, MockFxProvider())[0]) == 2
    wrong = other.model_copy(update={"segments": [segment.model_copy(update={"origin": "RIX"})]})
    assert "ITINERARY_MISMATCH" in compare([wrong], criteria(), NOW, MockFxProvider())[1][0].reason_codes


@pytest.fixture
def repository(tmp_path):
    return SearchRepository("sqlite:///" + str(tmp_path / "test.db"))


def test_api_history_and_validation(repository):
    with TestClient(create_app(settings=Settings(serpapi_api_key=None), repository=repository)) as client:
        response = client.post("/api/v1/searches", json=criteria().model_dump(mode="json"))
        assert response.status_code == 200
        result = response.json()
        assert result["data_mode"] == "MOCK"
        assert client.get("/api/v1/searches/" + result["search_id"]).json() == result
        assert len(client.get("/api/v1/searches").json()["items"]) == 1
        assert client.post("/api/v1/searches", json={}).status_code == 422
        assert client.get("/api/v1/searches/not-a-uuid").status_code == 422
        assert client.get("/api/v1/searches/00000000-0000-0000-0000-000000000000").status_code == 404
        bad = criteria().model_dump(mode="json") | {"data_mode": "REAL"}
        assert client.post("/api/v1/searches", json=bad).status_code == 503
        assert client.post("/api/v1/searches", json=bad | {"data_mode":"UNKNOWN"}).status_code == 422


async def test_agent_tool_cycle(repository):
    calls = []
    def handler(request):
        calls.append(request)
        name = "invent_prices" if len(calls) == 1 else "search_flights"
        return httpx.Response(200, json={"message": {"tool_calls": [{"function": {"name": name, "arguments": criteria().model_dump(mode="json")}}]}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as model:
        repository.initialize()
        from cheaper_air.agent.orchestrator import Agent, AgentMessage
        from cheaper_air.services.search import SearchService
        agent = Agent(Settings(), SearchService(repository), model)
        result = await agent.run(AgentMessage(message="Find MOCK flights"))
        assert len(calls) == 2
        assert result["status"] == "COMPLETED"
        assert "29.40" in result["explanation"]["summary"]


async def test_agent_clarification_and_limit(repository):
    from cheaper_air.agent.orchestrator import Agent, AgentMessage
    from cheaper_air.services.search import SearchService
    def handler(request):
        return httpx.Response(200, json={"message": {"tool_calls": [{"function": {
            "name": "request_clarification", "arguments": {"question": "Which year?", "missing_fields": ["departure_date"]}}}]}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as model:
        result = await Agent(Settings(), SearchService(repository), model).run(AgentMessage(message="February"))
        assert result["status"] == "NEEDS_CLARIFICATION"
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"message": {}}))) as model:
        with pytest.raises(ValueError, match="step limit"):
            await Agent(Settings(), SearchService(repository), model).run(AgentMessage(message="test"))


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL for real PostgreSQL integration")
def test_postgres_roundtrip():
    repository = SearchRepository(os.environ["TEST_DATABASE_URL"])
    with TestClient(create_app(repository=repository)) as client:
        result = client.post("/api/v1/searches", json=criteria().model_dump(mode="json")).json()
        assert client.get("/api/v1/searches/" + result["search_id"]).json() == result


async def test_schema_constrained_fallback(repository):
    from cheaper_air.agent.orchestrator import Agent, AgentMessage
    from cheaper_air.services.search import SearchService
    requests = []
    def handler(request):
        import json
        body = json.loads(request.content)
        requests.append(body)
        if "format" not in body:
            return httpx.Response(200, json={"message": {"content": "invalid native tool response"}})
        return httpx.Response(200, json={"message": {"content": json.dumps({"name": "search_flights", "search": criteria().model_dump(mode="json"), "clarification": None})}})
    repository.initialize()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as model:
        result = await Agent(Settings(), SearchService(repository), model).run(AgentMessage(message="Find flight"))
    assert len(requests) == 2
    assert "tools" not in requests[1]
    assert result["status"] == "COMPLETED"


async def test_miami_mock_comparison():
    query = criteria().model_copy(update={"destination": "MIA"})
    offers = await MockFlightProvider().search(query, NOW)
    assert offers and all(o.data_mode == "MOCK" for o in offers)
    assert all(o.segments[0].destination == "MIA" for o in offers)
    groups, excluded = compare(offers, query, NOW, MockFxProvider())
    assert groups[0].offers[0].total_eur == Decimal("726.80")
    assert groups[0].offers[0].savings_eur == Decimal("93.20")
    assert groups[0].offers[0].offer_id == "mock-us-standard"
    assert excluded[0].reason_codes == ["INSUFFICIENT_BAGGAGE"]


async def test_clarification_keeps_understood_destination(repository):
    from cheaper_air.agent.orchestrator import Agent, AgentMessage
    from cheaper_air.services.search import SearchService
    def handler(request):
        return httpx.Response(200, json={"message": {"tool_calls": [{"function": {
            "name": "request_clarification", "arguments": {
                "question": "Kada norite skristi?", "missing_fields": ["departure_date"],
                "interpreted_criteria": {"destination": "MIA"}}}}]}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as model:
        result = await Agent(Settings(), SearchService(repository), model).run(
            AgentMessage(message="noriu i majami", criteria_context={"origin": "VNO"}))
    assert result["interpreted_criteria"] == {"origin": "VNO", "destination": "MIA"}


def test_unsupported_route_is_explicit(repository):
    with TestClient(create_app(repository=repository)) as client:
        data = client.post("/api/v1/searches", json=criteria().model_dump(mode="json") | {"destination": "RIX"}).json()
        assert data["status"] == "NO_RESULTS"
        assert any("UNSUPPORTED_MOCK_ROUTE" in w for w in data["warnings"])
        assert data["offers"] == []

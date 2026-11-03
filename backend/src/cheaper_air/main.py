from contextlib import asynccontextmanager
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import httpx
from fastapi import FastAPI, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.exc import SQLAlchemyError
from cheaper_air.agent.orchestrator import Agent, AgentMessage
from cheaper_air.config import Settings
from cheaper_air.domain.models import SearchCriteria, SearchResult
from cheaper_air.persistence.repositories import SearchRepository
from cheaper_air.services.search import SearchService
from cheaper_air.services.airports import get_airport_catalog
from cheaper_air.providers.serpapi import SerpApiProvider
from cheaper_air.providers.errors import ProviderError
from cheaper_air.services.booking import BookingService


def create_app(settings=None, repository=None, agent_client=None, flight_client=None):
    settings = settings or Settings()
    repository = repository or SearchRepository(settings.database_url)
    provider = SerpApiProvider(settings.serpapi_api_key, flight_client)
    service = SearchService(repository, real_provider=provider)
    booking = BookingService(repository, provider)
    agent = Agent(settings, service, agent_client)

    @asynccontextmanager
    async def lifespan(app):
        repository.initialize()
        yield

    app = FastAPI(title="Cheaper Air", version="0.1.0", description="MOCK flight geo-pricing demonstrator", lifespan=lifespan)

    def error(code, message, status, details=None):
        return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "details": details or []}})

    @app.exception_handler(ProviderError)
    async def provider_error(request, exc):
        return error(exc.code, str(exc), exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return error("INVALID_REQUEST", "Request validation failed", 422, [{"loc": list(e["loc"]), "message": e["msg"]} for e in exc.errors()])

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        return error("INVALID_REQUEST", str(exc), 422)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        return error("DATABASE_UNAVAILABLE", "Database operation failed", 503)

    @app.exception_handler(httpx.HTTPError)
    async def model_error(request, exc):
        return error("OLLAMA_UNAVAILABLE", "Ollama request failed; structured search remains available", 504 if isinstance(exc, httpx.TimeoutException) else 503)

    @app.get("/api/v1/airports")
    def airports(q: str = Query("", max_length=120), limit: int = Query(10, ge=1, le=30)):
        catalog = get_airport_catalog()
        return {"items": catalog.search(q, limit), "metadata": catalog.metadata, "data_mode": "REFERENCE"}

    @app.get("/api/v1/airports/{code}")
    def airport(code: str):
        item = get_airport_catalog().get(code)
        return item if item else error("AIRPORT_NOT_FOUND", "Airport code is not in the global catalog", 404)

    @app.post("/api/v1/searches", response_model=SearchResult)
    async def search(criteria: SearchCriteria):
        return await service.search(criteria)

    @app.post("/api/v1/searches/{search_id}/observations/{observation_id}/booking-options")
    async def booking_options(search_id: UUID, observation_id: str):
        return await booking.options(search_id, observation_id)

    @app.get("/api/v1/booking-links/{quote_id}/{index}")
    async def booking_link(quote_id: UUID, index: int):
        return RedirectResponse(await booking.purchase_url(quote_id,index), status_code=303,
                                headers={"Cache-Control":"no-store", "Referrer-Policy":"no-referrer"})

    @app.get("/api/v1/searches")
    def history(limit: int = Query(20, ge=1, le=100), cursor: UUID | None = None):
        return repository.list(limit, str(cursor) if cursor else None)

    @app.get("/api/v1/searches/{search_id}", response_model=SearchResult, responses={404: {"description": "Search not found"}})
    def get_search(search_id: UUID):
        result = repository.get(str(search_id))
        return result if result else error("SEARCH_NOT_FOUND", "Search not found", 404)

    @app.post("/api/v1/agent/messages")
    async def message(body: AgentMessage):
        try:
            ZoneInfo(body.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Unknown timezone")
        return await agent.run(body)

    @app.get("/api/v1/capabilities")
    def capabilities():
        return {"airport_catalog": "GLOBAL", "mock": True,
                "real": {"provider": "serpapi-google-flights", "configured": bool(settings.serpapi_api_key and settings.serpapi_api_key.get_secret_value().strip()),
                         "max_localization_countries": 3, "verified_market_comparison": False}}

    @app.get("/api/v1/health/live")
    def live():
        return {"status": "ok", "data_mode": "MOCK"}

    @app.get("/api/v1/health/ready")
    async def ready():
        repository.ready()
        available = False
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                response = await client.get(settings.ollama_url + "/api/tags")
                response.raise_for_status()
                available = any(m.get("name") == settings.ollama_model for m in response.json().get("models", []))
        except (httpx.HTTPError, ValueError):
            pass
        return {"status": "ready" if available else "degraded", "structured_search": True, "agent": available, "data_mode": "MOCK"}

    return app


app = create_app()

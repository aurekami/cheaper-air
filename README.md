# Cheaper Air

**A local AI flight search agent that explores price differences across localized search results and connects selected itineraries to airline or agency offers.**

Built as a GitHub portfolio project with FastAPI, React, PostgreSQL and a local Ollama model. It combines a worldwide airport directory, deterministic price comparison, real API observations and seller handoffs. It does not purchase tickets.

![Cheaper Air dashboard — synthetic MOCK demonstration](docs/images/dashboard.png)

## What it does

- Searches a global airport directory by city, airport name, IATA, ICAO or local identifier.
- Interprets flight requests through a local Ollama agent with validated tools.
- Compares explicitly synthetic, fare-equivalent offers in **MOCK** mode.
- Retrieves Google Flights price observations through **SerpApi** in **REAL** mode.
- Checks sellers for a selected itinerary and provides an offer-specific purchase handoff when available.
- Shows observed prices, source timestamps, incomplete conditions and price changes explicitly.
- Saves search snapshots, exports results as JSON and maps actual itinerary airports and connections.

**Localization is not proof of point of sale.** A cheaper US-localized result does not establish that the same fare is available to every buyer. Real observations do not enter the verified savings calculation when baggage and fare conditions are unknown.

## Stack

| Layer | Technology |
| --- | --- |
| Backend | Python 3.12+, FastAPI, Pydantic |
| Local AI | Ollama, Qwen2.5-Coder 14B |
| Frontend | React 19, Vite, Tailwind CSS, Lucide |
| Map | d3-geo, topojson-client, world-atlas |
| Persistence | PostgreSQL, SQLAlchemy, psycopg |
| Flight observations | SerpApi Google Flights API |
| Airport reference | Bundled OurAirports snapshot |
| Verification | Pytest, HTTP test doubles, Playwright CLI checks |
| Local infrastructure | Docker Compose or Podman |

## Quick start

Requirements: Python 3.12+, Node.js 22+, npm, and Docker Compose or Podman. Ollama is optional for structured search. A SerpApi key is needed only for REAL flight searches.

```bash
git clone https://github.com/aurekami/cheaper-air.git
cd cheaper-air

python3 -m venv .venv
.venv/bin/pip install -e './backend[test]'
npm --prefix frontend ci
cp .env.example .env

docker compose up -d postgres
bash scripts/dev.sh
```

Open **[http://127.0.0.1:5173](http://127.0.0.1:5173)**. API documentation is at **[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)**. Stop the development servers with Ctrl+C. Compose currently runs PostgreSQL only; Python and React run locally.

### Podman alternative

If you do not use Docker Compose:

```bash
podman run -d --name cheaper-air-db \
  -e POSTGRES_USER=cheaper_air \
  -e POSTGRES_PASSWORD=cheaper_air \
  -e POSTGRES_DB=cheaper_air \
  -p 127.0.0.1:5432:5432 \
  -v cheaper-air-data:/var/lib/postgresql/data \
  docker.io/library/postgres:17
bash scripts/dev.sh
```

The example database credentials are for local development. The application creates its initial tables at startup; versioned migrations are not yet implemented. This is an unauthenticated local application, not an internet-facing production deployment.

## Try the demo without an API key

1. Choose **MOCK demo** as the data source.
2. Select **VNO → LHR**, a future departure date, and LT / UK / US markets.
3. Click **Compare MOCK fares**.
4. Review the baggage exclusion, comparable fares and calculated savings.
5. Open **Search history** to restore the original snapshot.

MOCK priced scenarios are VNO–LHR and VNO–MIA, with optional returns. Other directory airports remain searchable, but do not receive invented demo prices.

Example: the synthetic LT standard fare is EUR 240.00. The GB equivalent is GBP 180.00 at the synthetic rate 1.17 EUR/GBP: EUR 210.60, or EUR 29.40 below the baseline. The cheaper light fare is excluded when a checked bag is required. These numbers are not real travel offers.

## Enable real search

Create a [SerpApi account](https://serpapi.com/users/sign_up), then set this in the root `.env` file:

```dotenv
SERPAPI_API_KEY=your_private_key
```

Restart the backend after changing `.env`. A configured key makes REAL the default UI mode; MOCK remains an explicit choice. Missing credentials or provider failures never substitute synthetic results.

Select worldwide **IATA** airports, future dates and up to three localization countries. Examples include Warsaw (WAW/WMI) and Tokyo (HND/NRT). Airport selection does not guarantee that a supplier has available flights. Non-IATA directory records cannot be sent to this flight provider.

Each search makes up to one provider request per selected country. Seller checks may need up to three additional calls. Requests are user initiated; there is no background price crawler. API limits, availability and charges are controlled by your provider account.

REAL results request EUR directly and never use MOCK exchange rates. They preserve provider and retrieval timestamps because upstream results can be cached. A round-trip initial price is indicative until a return itinerary has been selected.

### Seller links

Click **Find sellers & buy** on an observed flight. The backend selects the cheapest returned matching return for that outbound, validates the complete itinerary and retrieves seller options. This is not an exhaustive cheapest-trip search across all possible flight combinations.

- A supplied seller price appears beside **Buy with seller**, with any difference from the initial observation.
- A seller link without a price is labelled **Check price with [seller]**. The initial estimate is never presented as a confirmed seller quote.
- Separate-ticket combinations and phone-only results are not advertised as single online purchase offers.
- Baggage descriptions are displayed, but a requested 23 kg bag is not automatically confirmed.
- Local handoff links expire after 20 minutes. No fare is held or reserved; checkout can still show changed prices or eligibility requirements.

Google booking POST actions preserve the provider's form-encoded body and resolve a standard redirect. The application does not scrape seller pages, bypass website protections, create orders or submit payments.

## Enable the local AI agent

Install [Ollama](https://ollama.com/) separately, then:

```bash
ollama pull qwen2.5-coder:14b
```

The default endpoint is `http://localhost:11434`. Change `OLLAMA_URL` or `OLLAMA_MODEL` in `.env` when necessary. Hardware requirements depend on model quantization and context size.

Open **AI flight search**. A request such as `noriu į Tokijų` uses the visible form's dates, origin and other selections. The agent can resolve worldwide airports and ask for clarification when a city has multiple airports. It cannot change the explicit REAL/MOCK mode or invent prices.

## Architecture

```mermaid
flowchart TD
    UI[React dashboard] --> API[FastAPI]
    API --> Agent[Bounded agent orchestrator]
    Agent <--> Ollama[Local Ollama model]
    Agent --> Search[Search service]
    API --> Search
    Search --> Airports[Global airport reference]
    Search --> Mock[MOCK provider + synthetic FX]
    Mock --> Compare[Deterministic equivalence and savings]
    Search --> Real[SerpApi price observations]
    API --> Sellers[Complete itinerary + seller lookup]
    Sellers --> Real
    API --> DB[(PostgreSQL snapshots)]
    Sellers --> Handoff[User-initiated seller handoff]
```

The model handles interpretation and tool selection. Python handles validation, money, equivalence and savings. REAL observations are separate from verified `Offer` / `ComparisonGroup` objects because the supplier may omit fare conditions.

## Tests and build

```bash
.venv/bin/python -m pytest backend/tests -q
npm --prefix frontend run build
```

The default tests use temporary SQLite and injected HTTP transports. They do not require Ollama or consume paid API credits. To include the PostgreSQL integration test, use a dedicated test database:

```bash
TEST_DATABASE_URL=postgresql+psycopg://cheaper_air:cheaper_air@localhost:5432/cheaper_air_test \
  .venv/bin/python -m pytest backend/tests -q
```

GitHub Actions provisions PostgreSQL, runs backend tests and builds the frontend. Browser flows were also checked through the Playwright CLI; a committed Playwright test-runner suite is still pending. See [verification notes](docs/ui-verification.md) for the distinction between synthetic tests and actual API checks.

One-country live smoke check, after configuring your key (consumes a provider request):

```bash
.venv/bin/python scripts/check_real_search.py --destination WAW --date 2027-02-12
```

Use a future date. This script does not make a booking.

## Airport data and attribution

The bundled [OurAirports](https://ourairports.com/data/) snapshot contains **86,335 airport/aerodrome records**, downloaded on 2026-11-03. It includes heliports and closed airports. Scheduled-service airports rank first; closed airports cannot be selected for flight search. Source data is public domain and has no accuracy or coverage guarantee.

Refresh deliberately with `python scripts/update_airports.py`, then restart the backend. The compressed snapshot and source/date/checksum metadata are shipped with the Python package. Map geometry comes from world-atlas / Natural Earth. The dashboard's dark visual direction was adapted from the author's Lected project.

## Roadmap and limits

- Add versioned database migrations, authentication and production deployment.
- Persist conversational history and richer tool audit records.
- Expand browser automation and itinerary-selection controls.
- Add further provider adapters after access and capabilities are verified.
- Establish genuine point-of-sale support and complete fare equivalence before claiming real geo-pricing savings.

KAYAK is a prospective supplier only. Its sandbox uses test-style data and production access requires partner approval. No KAYAK integration or credentials are included.

## More documentation

- [Architecture](docs/architecture.md)
- [Comparison rules](docs/comparison-rules.md)
- [API reference and examples](docs/api.md)
- [Verification notes](docs/ui-verification.md)

Secrets belong in `.env`, never browser code or Git. `.env`, local databases, browser output, dependencies and builds are excluded from version control.

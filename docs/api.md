# API and demonstrations

OpenAPI at `/openapi.json` is the source of truth for request schemas. Swagger UI is at `/docs`.

| Endpoint | Purpose |
| --- | --- |
| GET /api/v1/airports?q=city | Worldwide reference lookup; IATA, ICAO, names and cities |
| GET /api/v1/airports/{code} | Individual airport reference |
| POST /api/v1/searches | Execute/store MOCK comparisons or REAL SerpApi observations |
| GET /api/v1/capabilities | Global catalog and provider configuration, without credentials |
| GET /api/v1/searches | Paginated history, limit 1–100; opaque UUID cursor |
| GET /api/v1/searches/{id} | Full stored snapshot |
| POST /api/v1/agent/messages | Interpret text through Ollama tools |
| GET /api/v1/health/live | Process availability |
| GET /api/v1/health/ready | Database check and Ollama model availability |

Agent body example:

```json
{
  "message": "Find VNO to LHR on 12 February 2099, one adult economy, compare LT, GB and US with LT baseline, one 23 kg checked bag.",
  "timezone": "Europe/Vilnius",
  "locale": "lt-LT",
  "criteria_context": {}
}
```

Responses distinguish NEEDS_CLARIFICATION from COMPLETED. On clarification, send a new message with the previous explicit criteria in `criteria_context`. No server-side conversation memory is implemented. The locale field is reserved; the factual explanation currently uses Lithuanian.

Demo scenarios:

1. VNO–LHR, LT/GB/US, LT baseline: one standard group; GB cheapest; light fare excluded.
2. Any valid worldwide airport without MOCK inventory: NO_RESULTS, no invented replacement flights. Unknown/closed airport identifiers: HTTP 422.
3. GB/US plus DE baseline: PARTIAL, unsupported-market warning, null savings.
4. Invalid return date: HTTP 422. REAL with no API key: HTTP 503 / SERPAPI_NOT_CONFIGURED, no MOCK substitution.
5. Stop Ollama: structured search still works; agent requests return dependency errors.

History records original snapshots. Fetching an old search does not reprice or revalidate it. Clients must inspect expiry before interpreting an offer as current, even in MOCK mode.


REAL results include `observations` with provider identity, localization country, EUR price, local-time segments, retrieval/provider timestamps and `fare_conditions_verified=false`. They do not populate verified comparison groups. The source URL is limited to HTTPS Google Flights links. Initial round-trip results are explicitly marked incomplete because a return choice has not been made.

`SERPAPI_NOT_CONFIGURED`, `PROVIDER_AUTH_FAILED`, `PROVIDER_RATE_LIMIT`, `PROVIDER_UNAVAILABLE`, `PROVIDER_SEARCH_FAILED`, and `PROVIDER_RESPONSE_INVALID` return sanitized dependency errors. `PROVIDER_TIMEOUT` returns 504. More than three localization countries or a provider-unsupported non-IATA identifier returns 422. Partial country failures preserve successful observations and mark the search PARTIAL.


Seller flow endpoints:

- `POST /api/v1/searches/{search_id}/observations/{observation_id}/booking-options`: complete itinerary, seller names, nullable EUR prices, price changes and local purchase URLs. Retains the original observed price separately. No reservation is made.
- `GET /api/v1/booking-links/{quote_id}/{index}`: resolve the stored action and return a 303 redirect to the seller. Expired links return 410. Missing or unconfirmed itinerary/redirect data returns an explicit error rather than a generic search URL advertised as a purchase.

# Dashboard verification — 2026-11-03

Verified locally using Chromium through the Playwright CLI, the running FastAPI backend, PostgreSQL 17 and Ollama `qwen2.5-coder:14b`.

Passed browser assertions:

- Structured VNO–LHR search returns the expected synthetic EUR 210.60 fare and EUR 29.40 savings.
- Offer details open and close; the matched checked bag is 1 × 23 kg.
- Excluded light fare exposes its insufficient-baggage reason.
- History navigation restores the original saved comparison.
- Selecting New York's sales-market node changes the displayed price to EUR 225.40; selecting London restores its market.
- At a 390px viewport, the page does not overflow horizontally; search, details and history work. The wide data table scrolls within its own container.
- A natural-language request reaches the actual local model and completes the search through the backend.
- An unsupported route shows no comparable fares without substituting flights.
- A deliberately intercepted HTTP 503 shows the API error. Removing the interception allows the next search to succeed.
- JSON export creates a downloadable search snapshot.
- Methodology navigation opens and returns to the dashboard.

Backend suite: 12 passed with a real PostgreSQL round-trip test. Frontend production build: passed. The backend test client emits an upstream Starlette/httpx deprecation warning. The browser's deliberately simulated 503 emits the expected network error; this is part of the failure-state check.

Screenshots generated during local QA live in ignored `output/playwright/`. Browser checks above were executed through the CLI; they are not a committed Playwright test-runner suite. CI currently runs the backend tests and frontend build. Live flight APIs and bookability remain outside the implementation.

## Global routes and REAL adapter follow-up — 2026-11-03

Backend suite expanded to 41 passing tests with PostgreSQL enabled. New tests cover worldwide SerpApi request parameters, Warsaw/Tokyo aliases and airport choices, missing credentials, timeouts, partial localization failures, malformed results, round-trip incompleteness, no mock FX and no model-selected fallback to MOCK.

Browser checks passed for `varsuva` → WAW, `tokijas` → HND/NRT, explicit data-mode switching, and the actual missing-key 503 response. The REAL observation renderer was tested using an explicitly synthetic intercepted UI fixture, including source details, absent confirmed savings and a 390px viewport. The interception was removed and the page reloaded afterwards. No successful live SerpApi call is claimed: the local key is empty.

KAYAK public product pages were reviewed as a prospective additional supplier. Sandbox access is requested through its partner form and uses test-style data; production requires approval. No partner form was submitted, KAYAK credentials obtained or KAYAK adapter implemented.


## Seller links and dynamic map — 2026-11-03

Verified a real saved VNO–MIA round trip (2026-12-03 to 2027-01-05) through the US localization. Return selection and seller lookup succeeded; the response supplied an American seller POST action, baggage text and no seller price. The UI therefore treats it as an unpriced seller check. The handoff was tested without following the seller page and returned HTTP 303 to www.aa.com. The response used a standard HTML meta-refresh, now covered by regression tests. No ticket was purchased, no reservation was created and the earlier EUR 615 observation was not promoted to a confirmed seller price.

Playwright checks passed for destination/origin map updates (VNO–MIA, KUN–MIA), removal of fixed London/New York markers, priced/unpriced seller buttons, a changed-price indicator and 390px layout. Seller UI assertions used an explicitly synthetic intercepted response, removed afterwards.

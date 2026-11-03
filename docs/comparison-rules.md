# Comparison rules v1.0

- Only accepted, non-expired offers with known mandatory fees and complete relevant fare conditions are grouped.
- A group requires matching segment sequence, UTC timestamps, marketing/operating carrier and flight number, adult count and fare conditions.
- Fare product, cabin, checked/cabin baggage and refund/change rules must match exactly. An unknown rule is never assumed equal. A changeable/refundable fare must supply its penalty, including any currency.
- Checked baggage must meet the search requirement. Unknown baggage or missing FX excludes the offer.
- Prices are total itinerary prices for one adult, including mandatory fees. Fees dependent on payment or eligibility cannot be inferred.
- Money uses Decimal and ROUND_HALF_UP to two EUR decimal places. Synthetic rates are EUR per one source currency unit. The conversion is applied once to the total.
- The baseline is the cheapest comparable offer in the requested baseline market. Savings may be negative. Without a baseline, both savings fields are null.
- Offers sort by EUR price, then stable offer ID. Each equivalence group has its own winner; the system does not declare different fare conditions equivalent.
- Market is independent from currency. Cross-market eligibility is always UNKNOWN in V1. Synthetic expiration is 30 minutes after generation and does not prove real availability.

MOCK FX v1: EUR 1.00, GBP 1.17, USD 0.92 EUR per unit. These are invented demonstration rates, not financial market data.

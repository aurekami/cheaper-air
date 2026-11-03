from decimal import Decimal, ROUND_HALF_UP
from cheaper_air.domain.models import Money


class MockFxProvider:
    """Synthetic EUR per one currency unit; never a live exchange-rate source."""
    snapshot_id = "mock-fx-v1"
    rates = {"EUR": Decimal("1"), "GBP": Decimal("1.17"), "USD": Decimal("0.92")}

    def convert(self, money: Money) -> Decimal:
        return (money.amount * self.rates[money.currency]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

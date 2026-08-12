import pandas as pd

from app.data.providers import MarketDataProvider, ProviderError, fetch_with_retry
from app.models.domain import DataStatus


class FailingProvider(MarketDataProvider):
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    def get_daily_bars(self, symbol: str, limit: int = 300) -> pd.DataFrame:
        self.calls += 1
        raise self.error


def test_provider_timeout_is_bounded_and_fail_closed() -> None:
    provider = FailingProvider(TimeoutError())
    delays: list[float] = []
    result = fetch_with_retry(provider, "TEST", attempts=3, sleeper=delays.append)
    assert result.status == DataStatus.PROVIDER_DOWN and result.bars is None
    assert provider.calls == 3 and delays == [0.1, 0.2]


def test_provider_unavailable_is_fail_closed() -> None:
    result = fetch_with_retry(FailingProvider(ProviderError("down")), "TEST", attempts=1)
    assert result.status == DataStatus.PROVIDER_DOWN and result.error == "ProviderError"

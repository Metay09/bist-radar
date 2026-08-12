from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from app.data.providers import compare_latest_prices
from app.data.validation import DataValidator
from app.models.domain import DataStatus


def valid() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["TEST"] * 2,
            "timestamp": [datetime.now(UTC) - timedelta(minutes=1), datetime.now(UTC)],
            "open": [10.0, 11.0],
            "high": [12.0, 12.0],
            "low": [9.0, 10.0],
            "close": [11.0, 11.0],
            "volume": [100.0, 200.0],
        }
    )


def test_valid_data() -> None:
    assert DataValidator().validate(valid()).status == DataStatus.OK


def test_bad_ohlc() -> None:
    data = valid()
    data.loc[1, "low"] = 13
    assert DataValidator().validate(data).status == DataStatus.INVALID


def test_stale_data() -> None:
    data = valid()
    data["timestamp"] -= timedelta(days=5)
    assert DataValidator(timedelta(days=1)).validate(data).status == DataStatus.STALE


def test_duplicate_and_conflict() -> None:
    data = valid()
    data.loc[1, "timestamp"] = data.loc[0, "timestamp"]
    assert "duplicate bar" in DataValidator().validate(data).errors
    a = valid()
    b = valid()
    b.loc[1, "close"] = 11.01
    assert compare_latest_prices(a, b, 0.2)
    b.loc[1, "close"] = 12
    assert not compare_latest_prices(a, b, 0.2)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda d: d.__setitem__("timestamp", list(reversed(d.timestamp))), "bars out of order"),
        (lambda d: d.__setitem__("open", [-1.0, 11.0]), "non-positive price"),
        (lambda d: d.__setitem__("close", [0.0, 11.0]), "non-positive price"),
        (lambda d: d.__setitem__("volume", [100.0, -1.0]), "negative volume"),
        (lambda d: d.__setitem__("high", [8.0, 12.0]), "invalid OHLC"),
    ],
)
def test_invalid_market_data_boundaries(mutation: object, message: str) -> None:
    data = valid()
    mutation(data)  # type: ignore[operator]
    result = DataValidator().validate(data)
    assert result.status == DataStatus.INVALID
    assert message in result.errors
    assert 0 <= result.quality_score <= 100


def test_quality_score_is_always_bounded() -> None:
    data = valid()
    data.loc[:, ["open", "high", "low", "close", "volume"]] = -1
    data["symbol"] = "!"
    data["timestamp"] = [None, None]
    result = DataValidator().validate(data)
    assert 0 <= result.quality_score <= 100


def test_missing_and_remaining_invalid_cases() -> None:
    assert DataValidator().validate(pd.DataFrame()).status == DataStatus.MISSING
    data = valid()
    data["close"] = data["close"].astype(object)
    data.loc[1, "close"] = "bad"
    assert "non-numeric value" in DataValidator().validate(data).errors
    data = valid()
    data.loc[1, "symbol"] = "!"
    result = DataValidator().validate(data)
    assert "invalid symbol" in result.errors and "unexpected symbol" in result.errors
    data = valid()
    data.loc[1, "close"] = 100.0
    data.loc[1, "high"] = 101.0
    assert any("abnormal jump" in error for error in DataValidator().validate(data).errors)

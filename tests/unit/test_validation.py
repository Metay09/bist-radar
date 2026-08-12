from datetime import UTC, datetime, timedelta

import pandas as pd

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

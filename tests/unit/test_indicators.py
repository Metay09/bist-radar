import numpy as np
import pandas as pd

from app.indicators.technical import (
    atr,
    bollinger,
    distance_from_ema,
    ema,
    highest_high,
    lowest_low,
    macd,
    relative_volume,
    roc,
    rolling_volatility,
    rsi,
    sma,
    vwap,
)


def test_moving_averages() -> None:
    s = pd.Series(range(1, 11), dtype=float)
    assert sma(s, 3).iloc[-1] == 9
    assert round(ema(s, 3).iloc[-1], 3) == 9.002


def test_rsi_reference_behaviour() -> None:
    assert rsi(pd.Series(range(1, 30), dtype=float)).iloc[-1] == 100
    assert rsi(pd.Series([5.0] * 30)).iloc[-1] == 50


def test_macd() -> None:
    result = macd(pd.Series(range(100), dtype=float))
    assert result.iloc[-1]["macd"] > 0
    assert set(result) == {"macd", "signal", "histogram"}


def test_atr_known_constant_range() -> None:
    f = pd.DataFrame({"high": [11.0] * 20, "low": [9.0] * 20, "close": [10.0] * 20})
    assert atr(f).iloc[-1] == 2


def test_remaining_indicators() -> None:
    s = pd.Series(range(1, 31), dtype=float)
    f = pd.DataFrame({"high": s + 1, "low": s - 1, "close": s, "volume": [10.0] * 29 + [20.0]})
    assert relative_volume(f.volume, 20).iloc[-1] == 2
    assert roc(s, 10).iloc[-1] > 0
    assert highest_high(s, 5).iloc[-1] == 30
    assert lowest_low(s, 5).iloc[-1] == 26
    assert distance_from_ema(s, 5).iloc[-1] > 0
    assert rolling_volatility(s, 5).iloc[-1] >= 0
    assert bollinger(s).iloc[-1].upper > bollinger(s).iloc[-1].lower
    assert np.isfinite(vwap(f).iloc[-1])

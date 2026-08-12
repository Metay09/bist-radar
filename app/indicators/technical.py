import numpy as np
import pandas as pd


def sma(values: pd.Series, period: int) -> pd.Series:
    return values.rolling(period, min_periods=period).mean()


def ema(values: pd.Series, period: int) -> pd.Series:
    return values.ewm(span=period, adjust=False, min_periods=period).mean()


def rsi(values: pd.Series, period: int = 14) -> pd.Series:
    delta = values.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    result = 100 - (100 / (1 + rs))
    return result.mask((avg_loss == 0) & (avg_gain > 0), 100).mask(
        (avg_loss == 0) & (avg_gain == 0), 50
    )


def macd(values: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(values, fast) - ema(values, slow)
    signal_line = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({"macd": line, "signal": signal_line, "histogram": line - signal_line})


def true_range(frame: pd.DataFrame) -> pd.Series:
    previous = frame["close"].shift(1)
    return pd.concat(
        [(frame.high - frame.low), (frame.high - previous).abs(), (frame.low - previous).abs()],
        axis=1,
    ).max(axis=1)


def atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    return true_range(frame).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def bollinger(values: pd.Series, period: int = 20, deviations: float = 2) -> pd.DataFrame:
    middle = sma(values, period)
    std = values.rolling(period, min_periods=period).std(ddof=0)
    return pd.DataFrame(
        {"lower": middle - deviations * std, "middle": middle, "upper": middle + deviations * std}
    )


def vwap(frame: pd.DataFrame) -> pd.Series:
    typical = (frame.high + frame.low + frame.close) / 3
    return (typical * frame.volume).cumsum() / frame.volume.cumsum().replace(0, np.nan)


def relative_volume(volume: pd.Series, lookback: int = 20) -> pd.Series:
    expected = volume.shift(1).rolling(lookback, min_periods=lookback).mean()
    return volume / expected.replace(0, np.nan)


def roc(values: pd.Series, period: int = 10) -> pd.Series:
    return values.pct_change(period) * 100


def rolling_volatility(values: pd.Series, period: int = 20) -> pd.Series:
    return values.pct_change().rolling(period, min_periods=period).std(ddof=0)


def highest_high(values: pd.Series, period: int) -> pd.Series:
    return values.rolling(period, min_periods=period).max()


def lowest_low(values: pd.Series, period: int) -> pd.Series:
    return values.rolling(period, min_periods=period).min()


def distance_from_ema(values: pd.Series, period: int) -> pd.Series:
    baseline = ema(values, period)
    return (values / baseline - 1) * 100

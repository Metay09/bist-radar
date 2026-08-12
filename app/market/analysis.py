from enum import StrEnum

import pandas as pd

from app.indicators.technical import atr, ema, macd, relative_volume, roc, rolling_volatility, rsi


class Trend(StrEnum):
    STRONG_UPTREND = "STRONG_UPTREND"
    UPTREND = "UPTREND"
    NEUTRAL = "NEUTRAL"
    DOWNTREND = "DOWNTREND"
    STRONG_DOWNTREND = "STRONG_DOWNTREND"


class MarketRegime(StrEnum):
    RISK_ON = "RISK_ON"
    NEUTRAL = "NEUTRAL"
    RISK_OFF = "RISK_OFF"


def features(frame: pd.DataFrame) -> dict[str, float | bool]:
    close = frame.close
    e20, e50, e200 = ema(close, 20), ema(close, 50), ema(close, 200)
    m = macd(close)
    prior_high = frame.high.shift(1).rolling(20).max()
    prior_low = frame.low.shift(1).rolling(10).min()
    return {
        "price_above_ema20": bool(close.iloc[-1] > e20.iloc[-1]),
        "price_above_ema50": bool(close.iloc[-1] > e50.iloc[-1]),
        "price_above_ema200": bool(close.iloc[-1] > e200.iloc[-1]),
        "ema20_above_ema50": bool(e20.iloc[-1] > e50.iloc[-1]),
        "ema50_above_ema200": bool(e50.iloc[-1] > e200.iloc[-1]),
        "ema20_slope": float(e20.diff(5).iloc[-1]),
        "ema50_slope": float(e50.diff(5).iloc[-1]),
        "higher_high": bool(frame.high.iloc[-1] > frame.high.iloc[-6]),
        "higher_low": bool(frame.low.iloc[-1] > frame.low.iloc[-6]),
        "rsi": float(rsi(close).iloc[-1]),
        "macd_histogram": float(m.histogram.iloc[-1]),
        "macd_slope": float(m.macd.diff(3).iloc[-1]),
        "roc": float(roc(close).iloc[-1]),
        "rvol": float(relative_volume(frame.volume).iloc[-1]),
        "breakout": bool(close.iloc[-1] > prior_high.iloc[-1]),
        "close_quality": float(
            (close.iloc[-1] - frame.low.iloc[-1])
            / max(frame.high.iloc[-1] - frame.low.iloc[-1], 1e-9)
        ),
        "atr": float(atr(frame).iloc[-1]),
        "volatility": float(rolling_volatility(close).iloc[-1]),
        "recent_low": float(prior_low.iloc[-1]),
    }


def feature_table(frame: pd.DataFrame) -> pd.DataFrame:
    """Causal vector form of ``features`` for deterministic large replays."""
    close = frame.close
    e20, e50, e200 = ema(close, 20), ema(close, 50), ema(close, 200)
    m = macd(close)
    prior_high = frame.high.shift(1).rolling(20).max()
    prior_low = frame.low.shift(1).rolling(10).min()
    spread = (frame.high - frame.low).clip(lower=1e-9)
    return pd.DataFrame(
        {
            "price_above_ema20": close > e20,
            "price_above_ema50": close > e50,
            "price_above_ema200": close > e200,
            "ema20_above_ema50": e20 > e50,
            "ema50_above_ema200": e50 > e200,
            "ema20_slope": e20.diff(5),
            "ema50_slope": e50.diff(5),
            "higher_high": frame.high > frame.high.shift(5),
            "higher_low": frame.low > frame.low.shift(5),
            "rsi": rsi(close),
            "macd_histogram": m.histogram,
            "macd_slope": m.macd.diff(3),
            "roc": roc(close),
            "rvol": relative_volume(frame.volume),
            "breakout": close > prior_high,
            "close_quality": (close - frame.low) / spread,
            "atr": atr(frame),
            "volatility": rolling_volatility(close),
            "recent_low": prior_low,
        },
        index=frame.index,
    )


def classify_trend(f: dict[str, float | bool]) -> Trend:
    positives = sum(
        bool(f[key])
        for key in (
            "price_above_ema20",
            "price_above_ema50",
            "price_above_ema200",
            "ema20_above_ema50",
            "ema50_above_ema200",
            "higher_high",
            "higher_low",
        )
    )
    if positives >= 6 and float(f["ema20_slope"]) > 0:
        return Trend.STRONG_UPTREND
    if positives >= 4:
        return Trend.UPTREND
    if positives <= 1 and float(f["ema20_slope"]) < 0:
        return Trend.STRONG_DOWNTREND
    if positives <= 2:
        return Trend.DOWNTREND
    return Trend.NEUTRAL


def classify_regime(index: pd.DataFrame) -> MarketRegime:
    f = features(index)
    trend = classify_trend(f)
    if trend in {Trend.STRONG_UPTREND, Trend.UPTREND} and float(f["rsi"]) >= 50:
        return MarketRegime.RISK_ON
    if trend in {Trend.STRONG_DOWNTREND, Trend.DOWNTREND} and float(f["rsi"]) < 45:
        return MarketRegime.RISK_OFF
    return MarketRegime.NEUTRAL


def relative_strength(stock: pd.DataFrame, benchmark: pd.DataFrame, period: int = 20) -> float:
    return (
        float(stock.close.pct_change(period).iloc[-1] - benchmark.close.pct_change(period).iloc[-1])
        * 100
    )

import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from math import floor
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from app.indicators.technical import atr, ema, macd, roc, rolling_volatility, rsi
from app.models.domain import SignalClass
from app.scoring.radar import signal_class

FEATURE_SCHEMA_VERSION = "intraday-v1"
STRATEGY_ID = "radar-intraday-v1"
log = logging.getLogger(__name__)


def stage_a_eligible(frame: pd.DataFrame, minimum_history: int = 50) -> tuple[bool, str]:
    """Cheap quality screen; activity spikes are retained to avoid missing early movers."""
    if len(frame) < minimum_history:
        return False, "LIMITED_HISTORY"
    recent = frame.tail(20)
    nonzero_ratio = float((recent.volume > 0).mean())
    if nonzero_ratio < 0.8:
        positive_history = recent.volume.iloc[:-1][recent.volume.iloc[:-1] > 0]
        previous = float(positive_history.median()) if not positive_history.empty else 0.0
        spike = previous > 0 and float(recent.volume.iloc[-1]) >= previous * 3
        acceleration = abs(float(recent.close.pct_change().iloc[-1])) >= 0.02
        if not (spike and acceleration):
            return False, "LIQUIDITY_FILTER"
        return True, "EARLY_MOVER_OVERRIDE"
    return True, "ELIGIBLE"


class SignalLifecycle(StrEnum):
    SIGNAL_CREATED = "SIGNAL_CREATED"
    OUTCOME_PENDING = "OUTCOME_PENDING"
    PARTIALLY_LABELED = "PARTIALLY_LABELED"
    FULLY_LABELED = "FULLY_LABELED"


@dataclass(frozen=True)
class IntradaySnapshot:
    signal_id: str
    symbol: str
    timestamp: datetime
    timeframe: str
    price: float
    radar_score: int
    classification: str
    rsi: float
    macd: float
    macd_histogram: float
    rvol: float
    rvol_method: str
    atr: float
    vwap_distance: float
    ema9_distance: float
    ema20_distance: float
    ema50_distance: float
    breakout_distance: float
    relative_strength: float | None
    volume_acceleration: float
    price_acceleration: float
    market_regime: str
    daily_trend: str
    data_quality: float
    provider_latency_seconds: float
    early_momentum_score: int
    score_components: dict[str, int] | None = None
    rvol_sample_size: int = 0
    rvol_baseline: float | None = None
    rvol_quality: str = "INSUFFICIENT_DATA"
    rvol_is_outlier: bool = False
    feature_schema_version: str = FEATURE_SCHEMA_VERSION
    strategy_id: str = STRATEGY_ID

    def payload(self) -> dict[str, object]:
        return asdict(self)


def completed_intraday_bar(
    timestamp: datetime, timeframe_minutes: int, now: datetime, delay_minutes: int = 0
) -> bool:
    if timestamp.tzinfo is None or now.tzinfo is None:
        raise ValueError("timezone-aware timestamps required")
    return timestamp.astimezone(UTC) + timedelta(
        minutes=timeframe_minutes + delay_minutes
    ) <= now.astimezone(UTC)


def completed_frame(
    frame: pd.DataFrame, timeframe_minutes: int, now: datetime, delay_minutes: int = 0
) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    mask = [
        completed_intraday_bar(
            pd.Timestamp(ts).to_pydatetime(), timeframe_minutes, now, delay_minutes
        )
        for ts in frame.index
    ]
    return frame.loc[mask].copy()


def provider_latency(timestamps: list[datetime], received_at: datetime) -> dict[str, float]:
    if received_at.tzinfo is None or any(item.tzinfo is None for item in timestamps):
        raise ValueError("timezone-aware timestamps required")
    values = np.array(
        [
            (received_at.astimezone(UTC) - item.astimezone(UTC)).total_seconds()
            for item in timestamps
        ],
        dtype=float,
    )
    if not len(values):
        return {key: 0.0 for key in ("latest", "p50", "p95", "p99")}
    return {
        "latest": float(values[-1]),
        "p50": float(np.percentile(values, 50)),
        "p95": float(np.percentile(values, 95)),
        "p99": float(np.percentile(values, 99)),
    }


def _slot_rvol_details(
    frame: pd.DataFrame, lookback_days: int = 20, minimum_samples: int = 5
) -> tuple[pd.Series, pd.Series, pd.Series, str]:
    local_index = frame.index.tz_localize("UTC") if frame.index.tz is None else frame.index
    local_index = local_index.tz_convert(ZoneInfo("Europe/Istanbul"))
    slots = pd.Series(local_index.strftime("%H:%M"), index=frame.index)
    result = pd.Series(np.nan, index=frame.index, dtype=float)
    samples = pd.Series(0, index=frame.index, dtype=int)
    baselines = pd.Series(np.nan, index=frame.index, dtype=float)
    for slot in slots.unique():
        indexes = slots[slots == slot].index
        values = frame.loc[indexes, "volume"].astype(float)
        positive = values.where(values > 0)
        baseline = (
            positive.shift(1)
            .rolling(lookback_days, min_periods=min(minimum_samples, lookback_days))
            .mean()
        )
        count = positive.shift(1).rolling(lookback_days, min_periods=1).count().astype(int)
        baselines.loc[indexes], samples.loc[indexes] = baseline, count
        result.loc[indexes] = values / baseline
    return result, samples, baselines, "HISTORICAL_BAR_SLOT"


def slot_relative_volume(frame: pd.DataFrame, lookback_days: int = 20) -> tuple[pd.Series, str]:
    result, samples, _, method = _slot_rvol_details(frame, lookback_days)
    return result, method if int(samples.max()) >= 5 else "INSUFFICIENT_DATA"


def intraday_features(frame: pd.DataFrame) -> dict[str, float]:
    if len(frame) < 50:
        raise ValueError("WARMUP_INCOMPLETE")
    close = frame.close.astype(float)
    volume = frame.volume.astype(float)
    e9, e20, e50 = ema(close, 9), ema(close, 20), ema(close, 50)
    mac = macd(close)
    session = pd.Series(frame.index.date, index=frame.index)
    typical = (frame.high + frame.low + frame.close) / 3
    cumulative_value = (typical * volume).groupby(session).cumsum()
    cumulative_volume = volume.groupby(session).cumsum().replace(0, np.nan)
    session_vwap = cumulative_value / cumulative_volume
    rvol, rvol_samples, rvol_baselines, method = _slot_rvol_details(frame)
    prior_high = frame.high.shift(1).rolling(20).max()
    previous_day_high = frame.high.groupby(session).max().shift(1)
    prior_day = session.map(previous_day_high)
    last = -1
    price = float(close.iloc[last])
    price_returns = close.pct_change()
    values: dict[str, float] = {
        "rsi": float(rsi(close).iloc[last]),
        "macd": float(mac.macd.iloc[last]),
        "macd_histogram": float(mac.histogram.iloc[last]),
        "rvol": float(rvol.iloc[last]) if pd.notna(rvol.iloc[last]) else 0.0,
        "rvol_sample_size": float(rvol_samples.iloc[last]),
        "rvol_baseline": (
            float(rvol_baselines.iloc[last]) if pd.notna(rvol_baselines.iloc[last]) else 0.0
        ),
        "atr": float(atr(frame).iloc[last]),
        "vwap_distance": (price / float(session_vwap.iloc[last]) - 1) * 100,
        "ema9_distance": (price / float(e9.iloc[last]) - 1) * 100,
        "ema20_distance": (price / float(e20.iloc[last]) - 1) * 100,
        "ema50_distance": (price / float(e50.iloc[last]) - 1) * 100,
        "breakout_distance": (price / float(prior_high.iloc[last]) - 1) * 100,
        "day_high_distance": (price / float(frame.high.groupby(session).cummax().iloc[last]) - 1)
        * 100,
        "previous_day_high_distance": (
            (price / float(prior_day.iloc[last]) - 1) * 100
            if pd.notna(prior_day.iloc[last])
            else 0.0
        ),
        "volume_acceleration": float(volume.pct_change().iloc[last]),
        "price_acceleration": float(price_returns.diff().iloc[last]),
        "roc": float(roc(close, 4).iloc[last]),
        "rolling_volatility": float(rolling_volatility(close, 20).iloc[last]),
    }
    values["rvol_method"] = 1.0 if rvol_samples.iloc[last] >= 5 else 0.0
    return values


def early_momentum_score(feature: dict[str, float]) -> int:
    score = 0
    score += 18 if feature["rvol"] >= 1.5 else 9 if feature["rvol"] >= 1.0 else 0
    score += 15 if feature["volume_acceleration"] > 0.25 else 5
    score += 14 if feature["price_acceleration"] > 0 else 0
    score += 12 if feature["vwap_distance"] >= 0 else 0
    score += 12 if feature["ema9_distance"] >= 0 else 0
    score += 10 if feature["ema20_distance"] >= 0 else 0
    score += 12 if feature["breakout_distance"] >= -0.5 else 0
    score += 7 if feature["macd_histogram"] > 0 else 0
    return min(100, max(0, score))


def intraday_score_components(feature: dict[str, float]) -> dict[str, int]:
    """Setup-quality components; action/lifecycle state is deliberately absent."""
    rsi_value = feature["rsi"]
    momentum = max(0, min(20, floor((rsi_value - 35) / 1.75)))
    if rsi_value > 75:  # extended momentum is not exceptional setup quality
        momentum = max(8, momentum - floor((rsi_value - 75) / 2))
    trend = sum(
        6 for key in ("ema9_distance", "ema20_distance", "ema50_distance") if feature[key] >= 0
    )
    rv = feature["rvol"]
    volume = (
        0
        if feature.get("rvol_sample_size", 0) < 5
        else (
            18
            if rv >= 5
            else 16
            if rv >= 3
            else 14
            if rv >= 2
            else 11
            if rv >= 1.5
            else 6
            if rv >= 1
            else 2
        )
    )
    distance = feature["breakout_distance"]
    breakout = 14 if 0 <= distance <= 1 else 10 if -1 <= distance < 0 else 4
    return {
        "momentum": momentum,
        "trend": trend,
        "volume": volume,
        "breakout": breakout,
        "macd": 10 if feature["macd_histogram"] > 0 else 0,
        "vwap_quality": 8
        if 0 <= feature["vwap_distance"] <= 3
        else 3
        if feature["vwap_distance"] > 0
        else 0,
        "acceleration": 8 if feature["price_acceleration"] > 0 else 0,
    }


def intraday_radar_score(feature: dict[str, float]) -> int:
    return min(100, max(0, sum(intraday_score_components(feature).values())))


def scan_symbol(
    symbol: str,
    frame: pd.DataFrame,
    received_at: datetime,
    *,
    data_quality: float = 100,
    relative_strength: float | None = None,
    market_regime: str = "UNKNOWN",
    daily_trend: str = "UNKNOWN",
) -> IntradaySnapshot:
    feature = intraday_features(frame)
    if feature["rvol_sample_size"] < 5:
        log.debug(
            "insufficient_volume_baseline symbol=%s samples=%d",
            symbol,
            int(feature["rvol_sample_size"]),
        )
    elif feature["rvol"] > 15:
        log.warning(
            "rvol_outlier symbol=%s rvol=%.2f baseline=%.2f samples=%d",
            symbol,
            feature["rvol"],
            feature["rvol_baseline"],
            int(feature["rvol_sample_size"]),
        )
    score = intraday_radar_score(feature) if data_quality >= 90 else 0
    timestamp = pd.Timestamp(frame.index[-1]).to_pydatetime()
    if timestamp.tzinfo is None:
        raise ValueError("naive timestamp rejected")
    classification: SignalClass = signal_class(score)
    components = intraday_score_components(feature)
    return IntradaySnapshot(
        signal_id=f"{STRATEGY_ID}:{symbol}:{timestamp.isoformat()}",
        symbol=symbol,
        timestamp=timestamp,
        timeframe="15m",
        price=float(frame.close.iloc[-1]),
        radar_score=score,
        classification=classification.value,
        rsi=feature["rsi"],
        macd=feature["macd"],
        macd_histogram=feature["macd_histogram"],
        rvol=feature["rvol"],
        rvol_method=("HISTORICAL_BAR_SLOT" if feature["rvol_method"] else "INSUFFICIENT_DATA"),
        atr=feature["atr"],
        vwap_distance=feature["vwap_distance"],
        ema9_distance=feature["ema9_distance"],
        ema20_distance=feature["ema20_distance"],
        ema50_distance=feature["ema50_distance"],
        breakout_distance=feature["breakout_distance"],
        relative_strength=relative_strength,
        volume_acceleration=feature["volume_acceleration"],
        price_acceleration=feature["price_acceleration"],
        market_regime=market_regime,
        daily_trend=daily_trend,
        data_quality=data_quality,
        provider_latency_seconds=(received_at - timestamp.astimezone(UTC)).total_seconds(),
        early_momentum_score=early_momentum_score(feature),
        score_components=components,
        rvol_sample_size=int(feature["rvol_sample_size"]),
        rvol_baseline=feature["rvol_baseline"] or None,
        rvol_quality="OK" if feature["rvol_sample_size"] >= 5 else "INSUFFICIENT_DATA",
        rvol_is_outlier=feature["rvol"] > 15 and feature["rvol_sample_size"] >= 5,
    )

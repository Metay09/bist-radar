"""Point-in-time multi-timeframe feature computation."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

import pandas as pd

from app.ml.research_lab import FEATURE_MANIFEST, FeatureObservation, validate_feature_observation


def _atr(frame: pd.DataFrame, periods: int = 14) -> float | None:
    if frame.empty:
        return None
    close = frame.close.astype(float)
    previous = close.shift(1)
    tr = pd.concat(
        [
            (frame.high - frame.low).abs(),
            (frame.high - previous).abs(),
            (frame.low - previous).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return float(tr.tail(periods).mean())


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator - 1 if denominator else None


def build_point_in_time_features(
    signal_id: str,
    signal_time: datetime,
    frames: Mapping[str, pd.DataFrame],
    radar_context: Mapping[str, object],
    *,
    availability_times: Mapping[str, datetime],
    validated_xu100: pd.DataFrame | None = None,
) -> tuple[dict[str, float | int | None], list[FeatureObservation]]:
    """Use only rows whose provider availability is at or before signal_time."""
    usable: dict[str, pd.DataFrame] = {}
    for timeframe in ("5m", "15m", "60m", "1d"):
        frame = frames.get(timeframe)
        available_at = availability_times.get(timeframe)
        if frame is None or available_at is None or available_at > signal_time:
            usable[timeframe] = pd.DataFrame()
        else:
            usable[timeframe] = frame.loc[frame.index <= signal_time].copy()
    f5, f15, f60, daily = (usable[key] for key in ("5m", "15m", "60m", "1d"))
    values: dict[str, float | int | None] = {spec.name: None for spec in FEATURE_MANIFEST}
    if not f5.empty:
        close, volume = f5.close.astype(float), f5.volume.astype(float)
        typical = (f5.high.astype(float) + f5.low.astype(float) + close) / 3
        volume_sum = float(volume.sum())
        vwap = float((typical * volume).sum() / volume_sum) if volume_sum else 0.0
        values.update(
            {
                "micro_momentum_5m": _safe_ratio(float(close.iloc[-1]), float(close.iloc[-4]))
                if len(close) >= 4
                else None,
                "volume_acceleration_5m": _safe_ratio(
                    float(volume.iloc[-1]), float(volume.iloc[-9:-1].mean())
                )
                if len(volume) >= 9
                else None,
                "short_atr_5m": _atr(f5),
                "vwap_distance_5m": _safe_ratio(float(close.iloc[-1]), vwap),
                "ema_structure_5m": float(
                    close.ewm(span=9, adjust=False).mean().iloc[-1]
                    > close.ewm(span=20, adjust=False).mean().iloc[-1]
                    > close.ewm(span=50, adjust=False).mean().iloc[-1]
                )
                if len(close) >= 50
                else None,
            }
        )
        low, high = radar_context.get("entry_zone_low"), radar_context.get("entry_zone_high")
        if isinstance(low, (int, float)) and isinstance(high, (int, float)):
            width = max(float(high) - float(low), 1e-12)
            values["pullback_retest_quality_5m"] = max(
                0.0, 1 - abs(float(close.iloc[-1]) - (float(low) + float(high)) / 2) / width
            )
    if not f15.empty:
        close, volume = f15.close.astype(float), f15.volume.astype(float)
        raw_radar_score = radar_context.get("radar_score")
        prior_high = float(f15.high.astype(float).iloc[:-1].tail(20).max()) if len(f15) > 1 else 0.0
        values.update(
            {
                "radar_score_15m": float(raw_radar_score)
                if isinstance(raw_radar_score, (int, float))
                else None,
                "breakout_15m": _safe_ratio(float(close.iloc[-1]), prior_high),
                "rvol_15m": _safe_ratio(float(volume.iloc[-1]), float(volume.iloc[-21:-1].mean()))
                if len(volume) >= 21
                else None,
                "momentum_15m": _safe_ratio(float(close.iloc[-1]), float(close.iloc[-4]))
                if len(close) >= 4
                else None,
                "atr_15m": _atr(f15),
                "setup_age_15m": max(
                    0,
                    len(
                        f15.loc[
                            f15.index
                            > pd.Timestamp(radar_context.get("signal_timestamp", signal_time))
                        ]
                    ),
                ),
            }
        )
    if len(f60) >= 50:
        close = f60.close.astype(float)
        values["broader_trend_60m"] = float(
            close.ewm(span=20, adjust=False).mean().iloc[-1]
            > close.ewm(span=50, adjust=False).mean().iloc[-1]
        )
    if len(daily) >= 20:
        atr = pd.Series([_atr(daily.iloc[:index]) for index in range(2, len(daily) + 1)]).dropna()
        values["volatility_regime_daily"] = (
            float(atr.rank(pct=True).iloc[-1]) if not atr.empty else None
        )
    # Relative features remain UNKNOWN unless a validated, point-in-time index frame exists.
    if validated_xu100 is not None and len(f15) >= 2:
        index = validated_xu100.loc[validated_xu100.index <= signal_time]
        if len(index) >= 2:
            values["xu100_relative_return"] = float(
                f15.close.iloc[-1] / f15.close.iloc[-2]
                - index.close.iloc[-1] / index.close.iloc[-2]
            )
    observations: list[FeatureObservation] = []
    spec_by_name = {spec.name: spec for spec in FEATURE_MANIFEST}
    for name, value in values.items():
        timeframe = spec_by_name[name].source_timeframe
        source = signal_time
        available = (
            signal_time
            if timeframe == "cross_section"
            else availability_times.get(timeframe, signal_time)
        )
        observation = FeatureObservation(signal_id, name, source, available, value)
        validate_feature_observation(observation, signal_time)
        observations.append(observation)
    return values, observations


def add_cross_sectional_ranks(rows: list[dict[str, float | int | None]]) -> None:
    mapping = {
        "return_rank": "momentum_15m",
        "momentum_rank": "micro_momentum_5m",
        "rvol_rank": "rvol_15m",
        "liquidity_rank": "traded_value",
        "volatility_rank": "atr_15m",
    }
    for target, source in mapping.items():
        available: list[tuple[int, float]] = []
        for index, row in enumerate(rows):
            raw_value = row.get(source)
            if isinstance(raw_value, (int, float)):
                available.append((index, float(raw_value)))
        if not available:
            continue
        ranks = pd.Series([value for _, value in available]).rank(pct=True, method="average")
        for (index, _), rank in zip(available, ranks, strict=True):
            rows[index][target] = float(rank)

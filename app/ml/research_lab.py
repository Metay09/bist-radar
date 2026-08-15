"""Leakage-safe, shadow-only professional quant research primitives.

Nothing in this module is imported by the Radar scoring or execution paths.  It
may observe frozen decisions, but cannot mutate them or promote a model.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from hashlib import sha256
from math import log, sqrt
from statistics import median

import numpy as np

from app.ml.shadow import RadarDecision

CHAMPION_BASELINE_ID = "champion-adaptive-v1-2026-08-16"
CHAMPION_POLICY_VERSION = "adaptive-v1-h1-partial-trailing"
FEATURE_SCHEMA_VERSION = "quant-shadow-v1"
FORBIDDEN_FEATURE_TOKENS = (
    "future",
    "forward_return",
    "mfe",
    "mae",
    "target_hit",
    "terminal_result",
    "realized_r",
)


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    source_timeframe: str
    formula: str
    missing_policy: str = "UNKNOWN"
    authoritative_only: bool = False


FEATURE_MANIFEST: tuple[FeatureSpec, ...] = (
    FeatureSpec("micro_momentum_5m", "5m", "close[t]/close[t-3]-1"),
    FeatureSpec("pullback_retest_quality_5m", "5m", "distance/recovery around frozen entry zone"),
    FeatureSpec("volume_acceleration_5m", "5m", "volume[t]/mean(volume[t-8:t])"),
    FeatureSpec("short_atr_5m", "5m", "mean(true_range, 14)"),
    FeatureSpec("vwap_distance_5m", "5m", "close[t]/session_vwap[t]-1"),
    FeatureSpec("ema_structure_5m", "5m", "ordered EMA9/EMA20/EMA50 distances"),
    FeatureSpec("radar_score_15m", "15m", "frozen score_radar output"),
    FeatureSpec("breakout_15m", "15m", "close[t]/rolling_high[t-1]-1"),
    FeatureSpec("rvol_15m", "15m", "volume[t]/mean(prior comparable bars)"),
    FeatureSpec("momentum_15m", "15m", "close[t]/close[t-3]-1"),
    FeatureSpec("atr_15m", "15m", "mean(true_range, 14)"),
    FeatureSpec("setup_age_15m", "15m", "completed bars since signal"),
    FeatureSpec("broader_trend_60m", "60m", "EMA20/EMA50 structure at completed 60m bar"),
    FeatureSpec("volatility_regime_daily", "1d", "rolling ATR percentile from completed days"),
    FeatureSpec("return_rank", "cross_section", "timestamp-cohort percentile rank"),
    FeatureSpec("momentum_rank", "cross_section", "timestamp-cohort percentile rank"),
    FeatureSpec("rvol_rank", "cross_section", "timestamp-cohort percentile rank"),
    FeatureSpec("liquidity_rank", "cross_section", "timestamp-cohort traded-value rank"),
    FeatureSpec("volatility_rank", "cross_section", "timestamp-cohort ATR rank"),
    FeatureSpec(
        "xu100_relative_return",
        "cross_section",
        "symbol return - validated XU100 return",
        "UNKNOWN",
        True,
    ),
    FeatureSpec(
        "sector_relative_return",
        "cross_section",
        "symbol return - authoritative sector return",
        "UNKNOWN",
        True,
    ),
)


@dataclass(frozen=True)
class FeatureObservation:
    signal_id: str
    name: str
    source_timestamp: datetime
    availability_timestamp: datetime
    value: float | int | str | None


@dataclass(frozen=True)
class WalkForwardFold:
    fold: int
    train_dates: tuple[date, ...]
    validation_dates: tuple[date, ...]
    test_dates: tuple[date, ...]
    purged_dates: tuple[date, ...]
    embargo_sessions: int


@dataclass(frozen=True)
class ExpectedRShadow:
    expected_r: float | None
    q10_r: float | None
    q50_r: float | None
    q90_r: float | None
    confidence: str
    suggestion: str
    mode: str = "SHADOW"
    affects_radar: bool = False


def champion_manifest() -> dict[str, object]:
    return {
        "baseline_id": CHAMPION_BASELINE_ID,
        "policy_version": CHAMPION_POLICY_VERSION,
        "radar": "score_radar frozen behavior",
        "trade_plan": "immutable signal-time snapshot",
        "entry_exit": "adaptive-v1 completed-bar/next-open policy",
        "immutable": True,
        "historical_results": "append-only; never overwritten",
        "ml_mode": "shadow",
        "auto_promotion": False,
    }


def validate_feature_observation(observation: FeatureObservation, signal_time: datetime) -> None:
    lowered = observation.name.lower()
    if any(token in lowered for token in FORBIDDEN_FEATURE_TOKENS):
        raise ValueError(f"future-derived or target feature forbidden: {observation.name}")
    if observation.source_timestamp > signal_time:
        raise ValueError("feature source is after signal time")
    if observation.availability_timestamp > signal_time:
        raise ValueError("feature was not available at signal time")


def walk_forward_folds(
    sessions: Sequence[date],
    *,
    train_sessions: int,
    validation_sessions: int,
    test_sessions: int,
    purge_sessions: int = 1,
    embargo_sessions: int = 1,
) -> list[WalkForwardFold]:
    """Build expanding-window folds; a session is never split across partitions."""
    ordered = sorted(set(sessions))
    if min(train_sessions, validation_sessions, test_sessions) < 1:
        raise ValueError("positive partition sizes required")
    if min(purge_sessions, embargo_sessions) < 0:
        raise ValueError("purge and embargo cannot be negative")
    folds: list[WalkForwardFold] = []
    train_end = train_sessions
    while True:
        validation_start = train_end + purge_sessions
        validation_end = validation_start + validation_sessions
        test_start = validation_end + embargo_sessions
        test_end = test_start + test_sessions
        if test_end > len(ordered):
            break
        purged = ordered[train_end:validation_start] + ordered[validation_end:test_start]
        fold = WalkForwardFold(
            len(folds) + 1,
            tuple(ordered[:train_end]),
            tuple(ordered[validation_start:validation_end]),
            tuple(ordered[test_start:test_end]),
            tuple(purged),
            embargo_sessions,
        )
        if set(fold.train_dates) & set(fold.validation_dates + fold.test_dates):
            raise AssertionError("same-session leakage")
        folds.append(fold)
        train_end += test_sessions
    return folds


def data_hash(records: Iterable[dict[str, object]]) -> str:
    canonical = "\n".join(
        repr(sorted((str(key), value) for key, value in row.items())) for row in records
    )
    return sha256(canonical.encode()).hexdigest()


def ranking_metrics(actual: Sequence[int], scores: Sequence[float]) -> dict[str, float]:
    """Ranking-only metrics, suitable for Radar scores (never Brier/log loss)."""
    if len(actual) != len(scores) or not actual:
        raise ValueError("aligned non-empty samples required")
    y = np.asarray(actual, dtype=int)
    s = np.asarray(scores, dtype=float)
    order = np.argsort(-s, kind="stable")
    ranked = y[order]
    positives = int(y.sum())
    negatives = len(y) - positives
    tpr = np.r_[0.0, np.cumsum(ranked) / positives] if positives else np.array([0.0])
    fpr = np.r_[0.0, np.cumsum(1 - ranked) / negatives] if negatives else np.array([0.0])
    precision = np.cumsum(ranked) / np.arange(1, len(y) + 1)
    recall = np.cumsum(ranked) / positives if positives else np.zeros(len(y))
    top_n = max(1, int(np.ceil(len(y) * 0.1)))
    base = float(np.mean(y))
    return {
        "roc_auc": float(np.trapezoid(tpr, fpr)) if positives and negatives else 0.0,
        "pr_auc": float(np.trapezoid(np.r_[1.0, precision], np.r_[0.0, recall]))
        if positives
        else 0.0,
        "base_rate": base,
        "top_decile_lift": float(np.mean(ranked[:top_n]) / base) if base else 0.0,
    }


def regression_metrics(
    actual: Sequence[float], predicted: Sequence[float]
) -> dict[str, float | None]:
    if len(actual) != len(predicted) or not actual:
        raise ValueError("aligned non-empty samples required")
    y, p = np.asarray(actual), np.asarray(predicted)
    correlation = float(np.corrcoef(y, p)[0, 1]) if len(y) > 1 and y.std() and p.std() else None
    return {
        "mae": float(np.mean(np.abs(y - p))),
        "median_absolute_error": float(np.median(np.abs(y - p))),
        "r_correlation": correlation,
        "sign_accuracy_secondary": float(np.mean(np.sign(y) == np.sign(p))),
    }


def quantile_metrics(
    actual: Sequence[float], q10: Sequence[float], q50: Sequence[float], q90: Sequence[float]
) -> dict[str, float]:
    arrays = [np.asarray(item, dtype=float) for item in (actual, q10, q50, q90)]
    if not actual or len({len(item) for item in arrays}) != 1:
        raise ValueError("aligned non-empty samples required")
    y = arrays[0]

    def pinball(prediction: np.ndarray, quantile: float) -> float:
        error = y - prediction
        return float(np.mean(np.maximum(quantile * error, (quantile - 1) * error)))

    return {
        "pinball_q10": pinball(arrays[1], 0.1),
        "pinball_q50": pinball(arrays[2], 0.5),
        "pinball_q90": pinball(arrays[3], 0.9),
        "empirical_interval_coverage": float(np.mean((y >= arrays[1]) & (y <= arrays[3]))),
    }


def cost_adjust_r(
    gross_r: float, entry: float, risk_per_share: float, commission_bps: float, slippage_bps: float
) -> float:
    if entry <= 0 or risk_per_share <= 0:
        raise ValueError("positive entry and risk required")
    round_trip_cost = entry * 2 * (commission_bps + slippage_bps) / 10_000
    return gross_r - round_trip_cost / risk_per_share


def economic_metrics(
    realized_r: Sequence[float], durations_minutes: Sequence[float] = ()
) -> dict[str, float | int | None]:
    values = [float(value) for value in realized_r]
    if not values:
        return {
            "trade_count": 0,
            "mean_r": None,
            "median_r": None,
            "expected_r": None,
            "profit_factor": None,
            "max_drawdown_r": None,
            "time_in_trade_minutes": None,
        }
    equity, peak, drawdown = 0.0, 0.0, 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    gains = sum(value for value in values if value > 0)
    losses = -sum(value for value in values if value < 0)
    return {
        "trade_count": len(values),
        "mean_r": float(np.mean(values)),
        "median_r": median(values),
        "expected_r": float(np.mean(values)),
        "profit_factor": gains / losses if losses else None,
        "max_drawdown_r": drawdown,
        "time_in_trade_minutes": float(np.mean(durations_minutes)) if durations_minutes else None,
    }


def expected_r_shadow(
    q10: float | None,
    q50: float | None,
    q90: float | None,
    *,
    min_expected_r: float = 0.0,
    max_width: float = 2.0,
) -> ExpectedRShadow:
    if None in (q10, q50, q90):
        return ExpectedRShadow(None, q10, q50, q90, "LOW_CONFIDENCE", "NO_TRADE")
    assert q10 is not None and q50 is not None and q90 is not None
    if not q10 <= q50 <= q90:
        raise ValueError("quantiles must be monotonic")
    confidence = "LOW_CONFIDENCE" if q90 - q10 > max_width else "MODEL_ESTIMATE"
    suggestion = "TRADE" if q50 > min_expected_r and confidence != "LOW_CONFIDENCE" else "NO_TRADE"
    return ExpectedRShadow(q50, q10, q50, q90, confidence, suggestion)


def apply_research_shadow(decision: RadarDecision, _: ExpectedRShadow) -> RadarDecision:
    return decision


def disagreement_group(
    radar_score: float, ml_score: float, *, radar_cut: float, ml_cut: float
) -> str:
    radar = "HIGH" if radar_score >= radar_cut else "LOW"
    ml = "HIGH" if ml_score >= ml_cut else "LOW"
    return f"RADAR_{radar}_ML_{ml}"


def selection_risk(sharpes: Sequence[float]) -> dict[str, float | str]:
    """Conservative selection-risk diagnostic; full PBO needs enough strategy paths."""
    if len(sharpes) < 8:
        return {"status": "INSUFFICIENT", "trials": len(sharpes)}
    values = np.asarray(sharpes, dtype=float)
    best = float(values.max())
    expected_max_noise = sqrt(2 * log(len(values)))
    dispersion = float(values.std(ddof=1))
    return {
        "status": "DIAGNOSTIC_ONLY",
        "trials": len(values),
        "selection_penalty": expected_max_noise * dispersion,
        "deflated_sharpe_proxy": best - expected_max_noise * dispersion,
    }


def serializable_fold(fold: WalkForwardFold) -> dict[str, object]:
    payload = asdict(fold)
    for key in ("train_dates", "validation_dates", "test_dates", "purged_dates"):
        payload[key] = [item.isoformat() for item in payload[key]]
    return payload

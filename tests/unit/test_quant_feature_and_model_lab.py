from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from app.ml.feature_store import add_cross_sectional_ranks, build_point_in_time_features
from app.ml.model_lab import (
    classification_baselines_and_challenger,
    conditional_task_mask,
    quantile_challengers,
    regression_baselines_and_challenger,
)


def _frame(periods: int, frequency: str) -> pd.DataFrame:
    index = pd.date_range("2026-08-01", periods=periods, freq=frequency, tz="UTC")
    close = np.linspace(100, 120, periods)
    return pd.DataFrame(
        {
            "open": close - 0.2,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": np.linspace(1000, 3000, periods),
        },
        index=index,
    )


def test_point_in_time_multitimeframe_features_and_unknown_relatives() -> None:
    signal = datetime(2026, 8, 10, tzinfo=UTC)
    frames = {
        "5m": _frame(60, "5min"),
        "15m": _frame(60, "15min"),
        "60m": _frame(60, "1h"),
        "1d": _frame(30, "1D"),
    }
    available = {key: signal for key in frames}
    context = {
        "radar_score": 91,
        "entry_zone_low": 110,
        "entry_zone_high": 112,
        "signal_timestamp": signal,
    }
    features, observations = build_point_in_time_features(
        "s1", signal, frames, context, availability_times=available
    )
    assert features["radar_score_15m"] == 91
    assert features["micro_momentum_5m"] is not None
    assert features["xu100_relative_return"] is None
    assert features["sector_relative_return"] is None
    assert len(observations) == len(features)
    validated_index = _frame(60, "15min")
    relative, _ = build_point_in_time_features(
        "s2",
        signal,
        frames,
        context,
        availability_times=available,
        validated_xu100=validated_index,
    )
    assert relative["xu100_relative_return"] is not None


def test_unavailable_frame_fails_closed_and_cross_sectional_ranks() -> None:
    signal = datetime(2026, 8, 10, tzinfo=UTC)
    features, _ = build_point_in_time_features(
        "s", signal, {"5m": _frame(10, "5min")}, {}, availability_times={}
    )
    assert features["micro_momentum_5m"] is None
    rows = [
        {"momentum_15m": 1.0, "micro_momentum_5m": 2.0, "rvol_15m": 1.1, "atr_15m": 2.0},
        {"momentum_15m": 2.0, "micro_momentum_5m": 1.0, "rvol_15m": 1.2, "atr_15m": 3.0},
    ]
    add_cross_sectional_ranks(rows)
    assert rows[1]["return_rank"] == 1.0
    assert "liquidity_rank" not in rows[0]


def test_model_lab_baselines_challengers_calibration_and_quantiles() -> None:
    rng = np.random.default_rng(7)
    x = rng.normal(size=(180, 4))
    y = (x[:, 0] + x[:, 1] * 0.3 > 0).astype(int)
    result = classification_baselines_and_challenger(
        x[:100], y[:100], x[100:140], y[100:140], x[140:], y[140:]
    )
    assert result["base_rate"].display == "PROBABILITY"
    assert result["hist_gradient_boosting_raw"].display == "SHADOW_SCORE"
    assert result["logistic_calibrated"].display == "PROBABILITY"
    target = x[:, 0] - x[:, 1] * 0.5
    regressions = regression_baselines_and_challenger(x[:140], target[:140], x[140:], target[140:])
    assert set(regressions) == {"linear", "hist_gradient_boosting"}
    quantiles = quantile_challengers(x[:140], target[:140], x[140:], target[140:])
    assert "empirical_interval_coverage" in quantiles["metrics"]


def test_conditional_masks_and_single_class_rejection() -> None:
    entered = np.array([0, 1, 1])
    h1 = np.array([0, 1, 1])
    h2 = np.array([0, 0, 1])
    assert conditional_task_mask("entry", entered=entered, h1=h1, h2=h2).all()
    assert conditional_task_mask("stop", entered=entered, h1=h1, h2=h2).sum() == 2
    assert conditional_task_mask("h2", entered=entered, h1=h1, h2=h2).sum() == 2
    assert conditional_task_mask("h3", entered=entered, h1=h1, h2=h2).sum() == 1
    with pytest.raises(ValueError, match="both classes"):
        classification_baselines_and_challenger(
            np.ones((4, 2)), np.ones(4), np.ones((2, 2)), np.ones(2), np.ones((2, 2)), np.ones(2)
        )

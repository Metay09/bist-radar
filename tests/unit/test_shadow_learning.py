import pytest

from app.ml.shadow import (
    RadarDecision,
    ShadowPrediction,
    apply_shadow,
    base_rate_predictor,
    calibration,
    classification_metrics,
    decision_stump_predictor,
    logistic_predictor,
    sample_maturity,
    temporal_split,
)


def test_shadow_cannot_alter_radar_trade_or_risk() -> None:
    decision = RadarDecision(85, "STRONG_CANDIDATE", True, 98, 105, 50)
    prediction = ShadowPrediction({"stop_first": 0.99}, "hostile-model", "EARLY")
    assert apply_shadow(decision, prediction) is decision


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (0, "INSUFFICIENT_DATA"),
        (50, "EXPERIMENTAL"),
        (200, "EARLY"),
        (500, "MODERATE_SAMPLE"),
        (2000, "MATURE_SAMPLE"),
    ],
)
def test_sample_maturity(count: int, expected: str) -> None:
    assert sample_maturity(count) == expected


def test_temporal_split_has_no_future_leakage() -> None:
    train, validation, test = temporal_split(10)
    assert list(train) == list(range(6))
    assert max(train) < min(validation) < min(test)
    assert set(train).isdisjoint(test)


def test_probability_metrics_and_calibration() -> None:
    metrics = classification_metrics([0, 1, 1, 0], [0.1, 0.8, 0.7, 0.4])
    assert metrics["precision"] == 1
    assert metrics["recall"] == 1
    assert metrics["brier_score"] < 0.2
    assert metrics["roc_auc"] == 1
    buckets = calibration([0, 1, 1, 0], [0.1, 0.8, 0.7, 0.4])
    assert sum(int(item["count"]) for item in buckets) == 4


def test_deterministic_baseline_models() -> None:
    import numpy as np

    train_x = np.array([[0.0], [0.2], [0.8], [1.0]])
    train_y = np.array([0, 0, 1, 1])
    assert base_rate_predictor([0, 1], 2) == [0.5, 0.5]
    logistic = logistic_predictor(train_x, train_y, train_x)
    stump = decision_stump_predictor(train_x, train_y, train_x)
    assert logistic[0] < logistic[-1]
    assert stump == [0.0, 0.0, 1.0, 1.0]


def test_invalid_ml_inputs_rejected() -> None:
    with pytest.raises(ValueError):
        sample_maturity(-1)
    with pytest.raises(ValueError):
        temporal_split(-1)
    with pytest.raises(ValueError):
        classification_metrics([], [])
    with pytest.raises(ValueError):
        calibration([1], [])

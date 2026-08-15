"""Small, reproducible model laboratory for shadow challengers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LinearRegression, LogisticRegression

from app.ml.research_lab import quantile_metrics, ranking_metrics, regression_metrics
from app.ml.shadow import calibration, classification_metrics


@dataclass(frozen=True)
class ClassificationResult:
    model: str
    score: list[float]
    metrics: Mapping[str, object]
    display: str


@dataclass(frozen=True)
class RegressionResult:
    model: str
    prediction: list[float]
    metrics: Mapping[str, object]


def _classification_report(actual: np.ndarray, score: np.ndarray) -> dict[str, object]:
    report: dict[str, object] = dict(classification_metrics(actual.tolist(), score.tolist()))
    report.update(ranking_metrics(actual.tolist(), score.tolist()))
    bins = calibration(actual.tolist(), score.tolist())
    report["reliability_bins"] = bins
    report["calibration_gap"] = max(
        (abs(float(item["mean_probability"]) - float(item["hit_rate"])) for item in bins),
        default=None,
    )
    report["base_rate"] = float(np.mean(actual))
    return report


def classification_baselines_and_challenger(
    train_x: np.ndarray,
    train_y: np.ndarray,
    calibration_x: np.ndarray,
    calibration_y: np.ndarray,
    test_x: np.ndarray,
    test_y: np.ndarray,
) -> dict[str, ClassificationResult]:
    """Calibration is fitted before the untouched test block."""
    if len(np.unique(train_y)) < 2:
        raise ValueError("classification needs both classes in training")
    base = np.repeat(float(np.mean(train_y)), len(test_y))
    logistic = LogisticRegression(max_iter=1000, random_state=0).fit(train_x, train_y)
    hist = HistGradientBoostingClassifier(max_iter=150, learning_rate=0.05, random_state=0).fit(
        train_x, train_y
    )
    results = {
        "base_rate": ClassificationResult(
            "BASE_RATE", base.tolist(), _classification_report(test_y, base), "PROBABILITY"
        )
    }
    for name, model in (("logistic", logistic), ("hist_gradient_boosting", hist)):
        raw = model.predict_proba(test_x)[:, 1]
        results[f"{name}_raw"] = ClassificationResult(
            name.upper(), raw.tolist(), _classification_report(test_y, raw), "SHADOW_SCORE"
        )
        if len(np.unique(calibration_y)) >= 2:
            validation_score = model.predict_proba(calibration_x)[:, 1]
            # Platt head is fitted only on the later calibration block; the
            # underlying estimator remains frozen and test stays untouched.
            calibrated = LogisticRegression(random_state=0).fit(
                validation_score.reshape(-1, 1), calibration_y
            )
            probability = calibrated.predict_proba(raw.reshape(-1, 1))[:, 1]
            results[f"{name}_calibrated"] = ClassificationResult(
                f"{name.upper()}_CALIBRATED",
                probability.tolist(),
                _classification_report(test_y, probability),
                "PROBABILITY",
            )
    return results


def regression_baselines_and_challenger(
    train_x: np.ndarray, train_y: np.ndarray, test_x: np.ndarray, test_y: np.ndarray
) -> dict[str, RegressionResult]:
    linear = LinearRegression().fit(train_x, train_y)
    hist = HistGradientBoostingRegressor(max_iter=150, learning_rate=0.05, random_state=0).fit(
        train_x, train_y
    )
    output: dict[str, RegressionResult] = {}
    for name, model in (("linear", linear), ("hist_gradient_boosting", hist)):
        prediction = model.predict(test_x)
        output[name] = RegressionResult(
            name.upper(),
            prediction.tolist(),
            regression_metrics(test_y.tolist(), prediction.tolist()),
        )
    return output


def quantile_challengers(
    train_x: np.ndarray, train_y: np.ndarray, test_x: np.ndarray, test_y: np.ndarray
) -> dict[str, object]:
    predictions: dict[str, list[float]] = {}
    for quantile in (0.1, 0.5, 0.9):
        model = HistGradientBoostingRegressor(
            loss="quantile", quantile=quantile, max_iter=150, learning_rate=0.05, random_state=0
        ).fit(train_x, train_y)
        predictions[f"q{int(quantile * 100)}"] = model.predict(test_x).tolist()
    return {
        "predictions": predictions,
        "metrics": quantile_metrics(
            test_y.tolist(), predictions["q10"], predictions["q50"], predictions["q90"]
        ),
    }


def conditional_task_mask(
    task: Literal["entry", "stop", "h1", "h2", "h3"],
    *,
    entered: np.ndarray,
    h1: np.ndarray,
    h2: np.ndarray,
) -> np.ndarray:
    if task == "entry":
        return np.ones(len(entered), dtype=bool)
    if task in {"stop", "h1"}:
        return entered.astype(bool)
    if task == "h2":
        return h1.astype(bool)
    return h2.astype(bool)

from dataclasses import dataclass
from math import log

import numpy as np


@dataclass(frozen=True)
class RadarDecision:
    score: int
    classification: str
    open_trade: bool
    stop: float
    target: float
    quantity: float


@dataclass(frozen=True)
class ShadowPrediction:
    probabilities: dict[str, float]
    model_id: str
    sample_maturity: str
    mode: str = "SHADOW"


def apply_shadow(decision: RadarDecision, _: ShadowPrediction) -> RadarDecision:
    """Security boundary: predictions are never inputs to execution decisions."""
    return decision


def sample_maturity(count: int) -> str:
    if count < 0:
        raise ValueError("sample count cannot be negative")
    if count < 50:
        return "INSUFFICIENT_DATA"
    if count < 200:
        return "EXPERIMENTAL"
    if count < 500:
        return "EARLY"
    if count < 2000:
        return "MODERATE_SAMPLE"
    return "MATURE_SAMPLE"


def temporal_split(size: int) -> tuple[range, range, range]:
    if size < 0:
        raise ValueError("size cannot be negative")
    train_end = int(size * 0.6)
    validation_end = int(size * 0.8)
    return range(0, train_end), range(train_end, validation_end), range(validation_end, size)


def classification_metrics(actual: list[int], probability: list[float]) -> dict[str, float]:
    if len(actual) != len(probability) or not actual:
        raise ValueError("aligned non-empty samples required")
    clipped = np.clip(np.asarray(probability, dtype=float), 1e-12, 1 - 1e-12)
    observed = np.asarray(actual, dtype=int)
    predicted = clipped >= 0.5
    tp = int(((predicted == 1) & (observed == 1)).sum())
    fp = int(((predicted == 1) & (observed == 0)).sum())
    fn = int(((predicted == 0) & (observed == 1)).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    positives = int(observed.sum())
    negatives = len(observed) - positives
    order = np.argsort(-clipped)
    sorted_actual = observed[order]
    tpr = np.r_[0.0, np.cumsum(sorted_actual) / positives] if positives else np.array([0.0])
    fpr = np.r_[0.0, np.cumsum(1 - sorted_actual) / negatives] if negatives else np.array([0.0])
    roc_auc = float(np.trapezoid(tpr, fpr)) if positives and negatives else 0.0
    precision_curve = np.cumsum(sorted_actual) / np.arange(1, len(observed) + 1)
    recall_curve = np.cumsum(sorted_actual) / positives if positives else np.zeros(len(observed))
    pr_auc = (
        float(np.trapezoid(np.r_[1.0, precision_curve], np.r_[0.0, recall_curve]))
        if positives
        else 0.0
    )
    return {
        "roc_auc": roc_auc,
        "pr_auc": pr_auc,
        "brier_score": float(np.mean((clipped - observed) ** 2)),
        "log_loss": float(
            -np.mean(
                [y * log(p) + (1 - y) * log(1 - p) for y, p in zip(observed, clipped, strict=True)]
            )
        ),
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
    }


def calibration(actual: list[int], probability: list[float]) -> list[dict[str, float | int]]:
    if len(actual) != len(probability):
        raise ValueError("aligned samples required")
    buckets: list[dict[str, float | int]] = []
    for low in np.arange(0, 1, 0.1):
        selected = [
            (a, p) for a, p in zip(actual, probability, strict=True) if low <= p < low + 0.1
        ]
        if selected:
            buckets.append(
                {
                    "lower": float(low),
                    "upper": float(low + 0.1),
                    "count": len(selected),
                    "mean_probability": float(np.mean([p for _, p in selected])),
                    "hit_rate": float(np.mean([a for a, _ in selected])),
                }
            )
    return buckets


def base_rate_predictor(labels: list[int], size: int) -> list[float]:
    if not labels or size < 0:
        raise ValueError("training labels and non-negative size required")
    return [sum(labels) / len(labels)] * size


def logistic_predictor(
    train_x: np.ndarray, train_y: np.ndarray, predict_x: np.ndarray, steps: int = 200
) -> list[float]:
    """Small deterministic baseline implementation, intentionally not an optimizer for Radar."""
    if train_x.ndim != 2 or len(train_x) != len(train_y) or not len(train_y):
        raise ValueError("aligned training matrix required")
    mean = train_x.mean(axis=0)
    scale = train_x.std(axis=0)
    scale[scale == 0] = 1
    normalized = (train_x - mean) / scale
    weights = np.zeros(normalized.shape[1] + 1)
    design = np.c_[np.ones(len(normalized)), normalized]
    for _ in range(steps):
        probability = 1 / (1 + np.exp(-np.clip(design @ weights, -30, 30)))
        weights -= 0.05 * (design.T @ (probability - train_y)) / len(train_y)
    target = np.c_[np.ones(len(predict_x)), (predict_x - mean) / scale]
    return list(1 / (1 + np.exp(-np.clip(target @ weights, -30, 30))))


def decision_stump_predictor(
    train_x: np.ndarray, train_y: np.ndarray, predict_x: np.ndarray
) -> list[float]:
    if train_x.ndim != 2 or len(train_x) != len(train_y) or not len(train_y):
        raise ValueError("aligned training matrix required")
    base = float(np.mean(train_y))
    best_feature, best_threshold, best_loss = 0, float(np.median(train_x[:, 0])), float("inf")
    for feature in range(train_x.shape[1]):
        threshold = float(np.median(train_x[:, feature]))
        prediction = train_x[:, feature] >= threshold
        loss = float(np.mean((prediction - train_y) ** 2))
        if loss < best_loss:
            best_feature, best_threshold, best_loss = feature, threshold, loss
    left = train_y[train_x[:, best_feature] < best_threshold]
    right = train_y[train_x[:, best_feature] >= best_threshold]
    left_rate = float(np.mean(left)) if len(left) else base
    right_rate = float(np.mean(right)) if len(right) else base
    return [right_rate if row[best_feature] >= best_threshold else left_rate for row in predict_x]

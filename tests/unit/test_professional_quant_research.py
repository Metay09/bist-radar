from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest

from app.ml.registry import promotion_allowed
from app.ml.research_lab import (
    ExpectedRShadow,
    FeatureObservation,
    apply_research_shadow,
    champion_manifest,
    cost_adjust_r,
    data_hash,
    disagreement_group,
    economic_metrics,
    expected_r_shadow,
    quantile_metrics,
    ranking_metrics,
    regression_metrics,
    selection_risk,
    serializable_fold,
    validate_feature_observation,
    walk_forward_folds,
)
from app.ml.shadow import RadarDecision


def test_champion_is_immutable_shadow_only() -> None:
    manifest = champion_manifest()
    assert manifest["immutable"] is True
    assert manifest["ml_mode"] == "shadow"
    assert manifest["auto_promotion"] is False
    assert promotion_allowed({"all_metrics_pass": True}) is False


def test_feature_leakage_audit_rejects_future_and_target_features() -> None:
    signal = datetime(2026, 8, 14, 10, 30, tzinfo=UTC)
    validate_feature_observation(
        FeatureObservation("s", "momentum_15m", signal, signal, 0.1), signal
    )
    with pytest.raises(ValueError, match="not available"):
        validate_feature_observation(
            FeatureObservation("s", "momentum_15m", signal, signal + timedelta(seconds=1), 0.1),
            signal,
        )
    with pytest.raises(ValueError, match="forbidden"):
        validate_feature_observation(FeatureObservation("s", "mfe", signal, signal, 0.1), signal)


def test_walk_forward_keeps_sessions_isolated_and_embargoed() -> None:
    days = [date(2026, 1, 1) + timedelta(days=index) for index in range(20)]
    folds = walk_forward_folds(
        days,
        train_sessions=8,
        validation_sessions=3,
        test_sessions=2,
        purge_sessions=1,
        embargo_sessions=1,
    )
    assert len(folds) >= 2
    for fold in folds:
        train, validation, test = map(
            set, (fold.train_dates, fold.validation_dates, fold.test_dates)
        )
        assert not train & validation
        assert not train & test
        assert not validation & test
        assert len(fold.purged_dates) == 2


def test_radar_metrics_are_ranking_only() -> None:
    metrics = ranking_metrics([1, 0, 1, 0], [90, 80, 70, 60])
    assert "roc_auc" in metrics
    assert "top_decile_lift" in metrics
    assert "brier_score" not in metrics
    assert "log_loss" not in metrics


def test_cost_adjustment_and_expected_r_traceability() -> None:
    assert cost_adjust_r(1.0, 100, 5, 10, 5) == pytest.approx(0.94)
    shadow = expected_r_shadow(-0.5, 0.4, 0.9)
    assert shadow.expected_r == shadow.q50_r == 0.4
    assert shadow.suggestion == "TRADE"
    uncertain = expected_r_shadow(-2.0, 0.2, 2.0)
    assert uncertain.confidence == "LOW_CONFIDENCE"
    assert uncertain.suggestion == "NO_TRADE"


def test_shadow_expected_r_cannot_change_radar_action() -> None:
    decision = RadarDecision(93, "VERY_STRONG", True, 95, 110, 100)
    veto = ExpectedRShadow(-2, -3, -2, 1, "MODEL_ESTIMATE", "NO_TRADE")
    assert apply_research_shadow(decision, veto) is decision


def test_research_economic_regression_quantile_and_selection_metrics() -> None:
    assert data_hash([{"b": 2, "a": 1}]) == data_hash([{"a": 1, "b": 2}])
    regression = regression_metrics([1.0, -1.0, 0.5], [0.8, -0.7, 0.2])
    assert regression["mae"] == pytest.approx(0.266666, rel=1e-3)
    quantiles = quantile_metrics([0.0, 1.0], [-1.0, 0.0], [0.0, 1.0], [1.0, 2.0])
    assert quantiles["empirical_interval_coverage"] == 1
    economic = economic_metrics([1.0, -0.5, 0.25], [10, 20, 30])
    assert economic["trade_count"] == 3
    assert economic["max_drawdown_r"] == 0.5
    assert economic_metrics([])["trade_count"] == 0
    assert selection_risk([1.0])["status"] == "INSUFFICIENT"
    assert selection_risk(np.linspace(0.1, 1.0, 8).tolist())["status"] == "DIAGNOSTIC_ONLY"
    assert disagreement_group(90, 0.2, radar_cut=80, ml_cut=0.5) == "RADAR_HIGH_ML_LOW"
    with pytest.raises(ValueError, match="monotonic"):
        expected_r_shadow(1, 0, 2)
    assert expected_r_shadow(None, None, None).confidence == "LOW_CONFIDENCE"


def test_fold_serialization_and_invalid_split_inputs() -> None:
    days = [date(2026, 1, 1) + timedelta(days=index) for index in range(8)]
    fold = walk_forward_folds(days, train_sessions=3, validation_sessions=1, test_sessions=1)[0]
    assert serializable_fold(fold)["train_dates"][0] == "2026-01-01"
    with pytest.raises(ValueError, match="positive"):
        walk_forward_folds(days, train_sessions=0, validation_sessions=1, test_sessions=1)
    with pytest.raises(ValueError, match="cannot be negative"):
        walk_forward_folds(
            days,
            train_sessions=1,
            validation_sessions=1,
            test_sessions=1,
            purge_sessions=-1,
        )

import pytest

from app.market.analysis import MarketRegime, Trend
from app.models.domain import DataStatus, SignalClass
from app.scoring.radar import score_radar, signal_class

FEATURES = {
    "rsi": 65.0,
    "macd_histogram": 1.0,
    "roc": 5.0,
    "rvol": 3.2,
    "breakout": True,
    "close_quality": 0.9,
    "volatility": 0.02,
}


def test_high_score() -> None:
    result = score_radar("TEST", FEATURES, Trend.STRONG_UPTREND, MarketRegime.RISK_ON, 5, 2.5)
    assert (
        result.score >= 90
        and result.signal_class == SignalClass.VERY_STRONG_CANDIDATE
        and sum(result.components.values()) == result.score
    )


def test_fail_closed() -> None:
    result = score_radar(
        "TEST", FEATURES, Trend.STRONG_UPTREND, MarketRegime.RISK_ON, 5, 2.5, DataStatus.INVALID, 20
    )
    assert result.score == 0 and result.signal_class == SignalClass.NO_SIGNAL


def test_low_risk_reward_is_fail_closed() -> None:
    result = score_radar("TEST", FEATURES, Trend.STRONG_UPTREND, MarketRegime.RISK_ON, 5, 1.99)
    assert result.score == 0 and result.signal_class == SignalClass.NO_SIGNAL


def test_component_minimum_maximum_and_total_bounds() -> None:
    maximum = score_radar("MAX", FEATURES, Trend.STRONG_UPTREND, MarketRegime.RISK_ON, 100, 100)
    weak = {
        **FEATURES,
        "rsi": 0.0,
        "macd_histogram": -1.0,
        "roc": -50.0,
        "rvol": 0.0,
        "breakout": False,
        "close_quality": 0.0,
        "volatility": 1.0,
    }
    minimum = score_radar("MIN", weak, Trend.STRONG_DOWNTREND, MarketRegime.RISK_OFF, -100, 2)
    limits = {
        "trend": 15,
        "momentum": 15,
        "relative_volume": 20,
        "breakout": 15,
        "relative_strength": 10,
        "volatility": 5,
        "market_regime": 10,
        "risk_reward": 10,
    }
    for result in (minimum, maximum):
        assert 0 <= result.score <= 100
        assert result.score == sum(result.components.values())
        assert all(0 <= value <= limits[name] for name, value in result.components.items())


@pytest.mark.parametrize(
    "score, expected",
    [
        (0, SignalClass.NO_SIGNAL),
        (60, SignalClass.WATCH),
        (70, SignalClass.CANDIDATE),
        (80, SignalClass.STRONG_CANDIDATE),
        (90, SignalClass.VERY_STRONG_CANDIDATE),
        (100, SignalClass.VERY_STRONG_CANDIDATE),
    ],
)
def test_signal_class_boundaries(score: int, expected: SignalClass) -> None:
    assert signal_class(score) == expected

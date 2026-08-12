from app.market.analysis import MarketRegime, Trend
from app.models.domain import DataStatus, SignalClass
from app.scoring.radar import score_radar

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

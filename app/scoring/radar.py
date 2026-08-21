from dataclasses import dataclass

from app.market.analysis import MarketRegime, Trend
from app.models.domain import DataStatus, SignalClass

WEIGHTS = {
    "trend": 15,
    "momentum": 15,
    "relative_volume": 20,
    "breakout": 15,
    "relative_strength": 10,
    "volatility": 5,
    "market_regime": 10,
    "risk_reward": 10,
}


@dataclass
class RadarResult:
    symbol: str
    score: int
    signal_class: SignalClass
    components: dict[str, int]
    reasons: list[str]
    data_quality: float
    data_status: DataStatus


def signal_class(score: int) -> SignalClass:
    if score >= 90:
        return SignalClass.VERY_STRONG_CANDIDATE
    if score >= 80:
        return SignalClass.STRONG_CANDIDATE
    if score >= 70:
        return SignalClass.CANDIDATE
    if score >= 60:
        return SignalClass.WATCH
    return SignalClass.NO_SIGNAL


def score_radar(
    symbol: str,
    f: dict[str, float | bool],
    trend: Trend,
    regime: MarketRegime,
    relative_strength: float,
    risk_reward: float,
    data_status: DataStatus = DataStatus.OK,
    data_quality: float = 100,
    min_quality: float = 90,
) -> RadarResult:
    if data_status != DataStatus.OK or data_quality < min_quality or risk_reward < 2:
        return RadarResult(
            symbol,
            0,
            SignalClass.NO_SIGNAL,
            {key: 0 for key in WEIGHTS},
            ["Fail-closed: data or risk gate failed"],
            data_quality,
            data_status,
        )
    trend_score = {
        Trend.STRONG_UPTREND: 15,
        Trend.UPTREND: 11,
        Trend.NEUTRAL: 6,
        Trend.DOWNTREND: 2,
        Trend.STRONG_DOWNTREND: 0,
    }[trend]
    # Smooth enough that merely-positive, correlated indicators do not all saturate.
    momentum = min(15, max(0, round((float(f["rsi"]) - 40) / 4)))
    if float(f["macd_histogram"]) > 0:
        momentum += 2
    if float(f["roc"]) > 0:
        momentum += 1
    momentum = min(15, momentum)
    rv = float(f["rvol"])
    rvol_score = (
        20
        if rv >= 5
        else 17
        if rv >= 3
        else 14
        if rv >= 2
        else 11
        if rv >= 1.5
        else 7
        if rv >= 1
        else 2
    )
    breakout_score = (
        15
        if bool(f["breakout"]) and float(f["close_quality"]) >= 0.8
        else 7
        if bool(f["breakout"])
        else 2
    )
    components = {
        "trend": trend_score,
        "momentum": momentum,
        "relative_volume": rvol_score,
        "breakout": breakout_score,
        "relative_strength": min(10, max(0, round(5 + relative_strength))),
        "volatility": 4 if float(f["volatility"]) < 0.04 else 2,
        "market_regime": {
            MarketRegime.RISK_ON: 10,
            MarketRegime.NEUTRAL: 6,
            MarketRegime.RISK_OFF: 1,
        }[regime],
        "risk_reward": min(10, max(4, round((risk_reward - 1) * 3))),
    }
    total = min(100, sum(components.values()))
    reasons = [
        f"Trend: {trend}",
        f"Relative volume: {rv:.2f}x",
        "Positive MACD momentum" if float(f["macd_histogram"]) > 0 else "Negative MACD momentum",
        "Resistance breakout confirmed" if breakout_score == 15 else "No confirmed breakout",
        f"Market regime: {regime}",
    ]
    return RadarResult(
        symbol, total, signal_class(total), components, reasons, data_quality, data_status
    )

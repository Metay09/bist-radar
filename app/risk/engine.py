from decimal import ROUND_DOWN, Decimal

from app.models.domain import TradePlan

D = Decimal
DEFAULT_ATR_MULTIPLIER = D("1.2")
DEFAULT_RISK_PERCENT = D("0.75")
DEFAULT_MAX_POSITION_PERCENT = D("20")
MIN_STOP_DISTANCE_PERCENT = D("0.10")


def calculate_stop(
    entry: Decimal,
    atr: Decimal,
    recent_swing_low: Decimal,
    atr_multiplier: Decimal = DEFAULT_ATR_MULTIPLIER,
) -> tuple[Decimal, str]:
    if entry <= 0 or atr <= 0 or recent_swing_low <= 0:
        raise ValueError("positive entry, ATR and swing low required")
    stop = min(recent_swing_low, entry - atr * atr_multiplier)
    if stop <= 0 or stop >= entry:
        raise ValueError("invalid stop")
    return stop.quantize(D("0.01")), "below_recent_swing_and_1_2_ATR"


def build_trade_plan(entry: Decimal, atr: Decimal, recent_swing_low: Decimal) -> TradePlan:
    stop, reason = calculate_stop(entry, atr, recent_swing_low)
    risk = entry - stop
    return TradePlan(
        entry,
        stop,
        (entry + risk * D("1.5")).quantize(D("0.01")),
        (entry + risk * D("2.5")).quantize(D("0.01")),
        D("2.5"),
        reason,
    )


def position_size(
    account_equity: Decimal,
    entry: Decimal,
    stop: Decimal,
    risk_percent: Decimal = DEFAULT_RISK_PERCENT,
    max_position_percent: Decimal = DEFAULT_MAX_POSITION_PERCENT,
) -> Decimal:
    if account_equity <= 0 or entry <= 0 or stop <= 0 or stop >= entry:
        raise ValueError("invalid sizing inputs")
    if (entry - stop) / entry * 100 < MIN_STOP_DISTANCE_PERCENT:
        raise ValueError("stop distance is extremely small")
    risk_budget = account_equity * risk_percent / 100
    shares = (risk_budget / (entry - stop)).to_integral_value(rounding=ROUND_DOWN)
    cap = (account_equity * max_position_percent / 100 / entry).to_integral_value(
        rounding=ROUND_DOWN
    )
    return min(shares, cap)

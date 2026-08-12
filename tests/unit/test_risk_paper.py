from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.paper.ledger import PaperLedger
from app.risk.engine import build_trade_plan, calculate_stop, position_size


def test_stop_calculation() -> None:
    stop, reason = calculate_stop(Decimal("26.40"), Decimal("0.50"), Decimal("25.80"))
    assert stop == Decimal("25.80") and "ATR" in reason


def test_position_sizing_capped() -> None:
    assert position_size(Decimal("100000"), Decimal("100"), Decimal("95")) == Decimal("150")
    with pytest.raises(ValueError):
        position_size(Decimal("100"), Decimal("10"), Decimal("10"))
    with pytest.raises(ValueError):
        position_size(Decimal("0"), Decimal("10"), Decimal("9"))
    with pytest.raises(ValueError, match="extremely small"):
        position_size(Decimal("100000"), Decimal("100"), Decimal("99.99"))


def test_position_limit_never_overflows() -> None:
    for equity in (Decimal("100"), Decimal("10000"), Decimal("1000000")):
        size = position_size(equity, Decimal("10"), Decimal("9"))
        assert size * Decimal("10") <= equity * Decimal("0.20")


def test_invalid_stop_boundaries() -> None:
    for entry, atr_value, swing in [
        (Decimal("10"), Decimal("0"), Decimal("9")),
        (Decimal("10"), Decimal("1"), Decimal("0")),
    ]:
        with pytest.raises(ValueError):
            calculate_stop(entry, atr_value, swing)


def test_trade_plan_and_paper_trade() -> None:
    plan = build_trade_plan(Decimal("26.40"), Decimal("0.50"), Decimal("25.80"))
    assert plan.risk_reward == Decimal("2.5")
    ledger = PaperLedger()
    now = datetime.now(UTC)
    trade = ledger.open(
        "TEST", now, plan.entry, Decimal("10"), plan.stop, plan.target_1, plan.target_2
    )
    closed = ledger.close(trade.trade_id, now, Decimal("28"), "target")
    assert closed.net_return > 0 and ledger.performance()["win_rate"] == 1
    with pytest.raises(ValueError):
        ledger.close(trade.trade_id, now, Decimal("28"), "again")

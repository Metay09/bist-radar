from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.risk.trade_plan_view import build_research_trade_plan


def plan(distance: float, *, age_minutes: int = 0, lows: list[object] | None = None):  # type: ignore[no-untyped-def]
    now = datetime(2026, 8, 13, 12, tzinfo=UTC)
    return build_research_trade_plan(
        {
            "symbol": "ASELS",
            "timestamp": now - timedelta(minutes=age_minutes),
            "price": 100,
            "atr": 1,
            "breakout_distance": distance,
            "rvol": 2.5,
            "vwap_distance": 1,
            "ema9_distance": 1,
            "ema20_distance": 1,
        },
        lows or [98],
        account_equity=Decimal("100000"),
        risk_percent=Decimal("0.75"),
        max_position_percent=Decimal("20"),
        now=now,
    )


@pytest.mark.parametrize(
    ("distance", "expected"),
    [
        (1, "GIRIS_BEKLENIYOR"),
        (0.1, "GIRIS_BOLGESINDE"),
        (-0.2, "BREAKOUT_ONAYI"),
        (-1, "KACMIS_KOVALAMA"),
        (20, "GECERSIZ"),
    ],
)
def test_trade_plan_status_classification(distance: float, expected: str) -> None:
    lows = [119] if distance == 20 else None
    assert plan(distance, lows=lows)["status"] == expected


def test_trade_plan_risk_reward_position_math_and_stale_warning() -> None:
    result = plan(0.1, age_minutes=180)
    assert result["risk_reward"] == 2.5
    assert result["stale"] is True
    assert result["position_sizing"]["allowed_risk_amount"] == 750  # type: ignore[index]
    assert result["position_sizing"]["estimated_quantity"] > 0  # type: ignore[index,operator]
    assert any("Veri eski" in item for item in result["explanation"])  # type: ignore[union-attr]
    target = result["targets"][0]  # type: ignore[index]
    assert target["return_percent"] > 0


def test_trade_plan_missing_context_fails_closed() -> None:
    result = build_research_trade_plan(
        {"symbol": "NONE"},
        [],
        account_equity=Decimal("100000"),
        risk_percent=Decimal("0.75"),
        max_position_percent=Decimal("20"),
    )
    assert result["status"] == "GECERSIZ"
    assert "reference_price" not in result

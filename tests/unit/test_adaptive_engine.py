from datetime import UTC, datetime, timedelta

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.adaptive.engine import AdaptiveConfig, evaluate_adaptive_setup
from app.adaptive.service import AdaptiveDecisionService
from app.database.base import AdaptiveEventRow, AdaptivePlanVersionRow, AdaptiveSetupRow, Base


def frame(prices: list[tuple[float, float, float, float]], start: datetime) -> pd.DataFrame:
    index = pd.date_range(start, periods=len(prices), freq="15min")
    return pd.DataFrame(
        [{"open": o, "high": h, "low": low, "close": c, "volume": 1000} for o, h, low, c in prices],
        index=index,
    )


PLAN = {
    "entry_zone_low": 99.0,
    "entry_zone_high": 101.0,
    "stop_price": 98.0,
    "targets": [{"price": 104.0}, {"price": 106.0}, {"price": 108.0}],
}
FEATURES = {"rvol": 1.5, "atr": 1.0, "radar_score": 80}


def test_setup_cannot_wait_forever_and_signal_bar_cannot_enter() -> None:
    start = datetime(2026, 1, 5, 7, tzinfo=UTC)
    data = frame([(105, 106, 104, 105)] * 12, start)
    signal = data.index[0].to_pydatetime()
    result = evaluate_adaptive_setup(
        signal,
        data,
        FEATURES,
        PLAN,
        data.index[-1].to_pydatetime() + timedelta(minutes=15),
        config=AdaptiveConfig(entry_ttl_bars=4),
    )
    assert result.outcome in {"NO_ENTRY_EXPIRED", "CHASED"}
    assert result.entry_time is None
    assert all(event["event_time"] > signal for event in result.events[1:])


def test_entry_then_same_bar_hard_stop_is_conservative() -> None:
    start = datetime(2026, 1, 5, 7, tzinfo=UTC)
    prices = [(100, 101, 99, 100), (100, 101, 99, 100), (100, 105, 97, 103)]
    data = frame(prices, start)
    result = evaluate_adaptive_setup(
        data.index[0].to_pydatetime(),
        data,
        FEATURES,
        PLAN,
        data.index[-1].to_pydatetime() + timedelta(minutes=15),
    )
    assert result.entry_time == data.index[2].to_pydatetime()
    assert result.outcome == "STOP_BEFORE_H1"
    assert result.initial_stop == 98
    assert result.exit_price == 98


def test_invalid_setup_touch_does_not_activate() -> None:
    start = datetime(2026, 1, 5, 7, tzinfo=UTC)
    history = [(110 - i, 111 - i, 108 - i, 109 - i) for i in range(12)]
    data = frame(history, start)
    signal = data.index[7].to_pydatetime()
    result = evaluate_adaptive_setup(
        signal, data, FEATURES, PLAN, data.index[-1].to_pydatetime() + timedelta(minutes=15)
    )
    assert result.entry_time is None
    assert result.outcome in {"NO_ENTRY_STRUCTURE", "NO_ENTRY_DECAY", "CHASED"}


def test_stalled_trade_time_exits_next_open() -> None:
    start = datetime(2026, 1, 5, 7, tzinfo=UTC)
    prices = [(100, 101, 99, 100)] * 12
    data = frame(prices, start)
    result = evaluate_adaptive_setup(
        data.index[0].to_pydatetime(),
        data,
        FEATURES,
        PLAN,
        data.index[-1].to_pydatetime() + timedelta(minutes=15),
        config=AdaptiveConfig(max_holding_bars=4),
    )
    assert result.outcome == "TIME_EXIT_FLAT"
    assert result.state == "TIME_EXIT"
    assert result.exit_time is not None
    assert any(event["event_type"] == "TRADE_STALLED" for event in result.events)


def test_h1_tightens_stop_and_never_increases_risk() -> None:
    start = datetime(2026, 1, 5, 7, tzinfo=UTC)
    prices = [(100, 101, 99, 100), (100, 101, 99, 100), (100, 104.5, 99, 104)]
    data = frame(prices, start)
    result = evaluate_adaptive_setup(
        data.index[0].to_pydatetime(),
        data,
        FEATURES,
        PLAN,
        data.index[-1].to_pydatetime() + timedelta(minutes=15),
    )
    stops = [
        event["payload"]["new_stop"]
        for event in result.events
        if event["event_type"] == "STOP_TIGHTENED"
    ]
    assert stops and stops == sorted(stops)
    assert all(stop >= result.initial_stop for stop in stops)


def test_adaptive_read_models_and_analytics() -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    stamp = datetime(2026, 1, 5, 7, tzinfo=UTC)
    with factory.begin() as session:
        session.add(
            AdaptiveSetupRow(
                setup_id="adaptive:s1",
                signal_id="s1",
                symbol="ASELS",
                policy_version="adaptive-v1",
                state="TIME_EXIT",
                health="ZAYIFLIYOR",
                signal_time=stamp,
                entry_time=stamp + timedelta(minutes=30),
                entry_price=100,
                initial_stop=98,
                active_stop=100,
                exit_time=stamp + timedelta(hours=2),
                exit_price=101,
                outcome="TIME_EXIT_PROFIT",
                highest_target=1,
                action={"action": "ZAMAN_CIKISI"},
                metrics={"realized_r_after_cost": 0.49},
                config={"entry_ttl_bars": 8},
                updated_at=stamp + timedelta(hours=2),
            )
        )
        session.add(
            AdaptivePlanVersionRow(
                setup_id="adaptive:s1",
                version=1,
                created_at=stamp,
                effective_at=stamp,
                reason="SIGNAL_PLAN",
                plan=PLAN,
            )
        )
        session.add_all(
            [
                AdaptiveEventRow(
                    setup_id="adaptive:s1",
                    sequence=1,
                    event_time=stamp,
                    event_type="SIGNAL_DETECTED",
                    state_to="DETECTED",
                    payload={},
                ),
                AdaptiveEventRow(
                    setup_id="adaptive:s1",
                    sequence=2,
                    event_time=stamp + timedelta(hours=1),
                    event_type="H1_TOUCHED",
                    state_from="ACTIVE",
                    state_to="H1_REACHED",
                    payload={},
                ),
            ]
        )
    service = AdaptiveDecisionService(factory)
    detail = service.detail("ASELS")
    assert detail and detail["outcome"] == "TIME_EXIT_PROFIT"
    assert service.detail("MISSING") is None
    analytics = service.analytics()
    assert analytics["entry_activated"] == 1
    assert analytics["median_time_to_entry_minutes"] == 30
    assert analytics["static_vs_adaptive_oos"]["adaptive_is_better"] is False

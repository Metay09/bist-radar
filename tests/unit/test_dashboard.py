from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import dashboard
from app.api.dashboard import freshness, market_open
from app.database.base import (
    Base,
    MarketBarRow,
    MlFeatureSnapshotRow,
    PaperTradeRow,
    WorkerStateRow,
)


def test_freshness_states(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    assert freshness(None)["state"] == "UNKNOWN"
    monkeypatch.setattr("app.api.dashboard.market_open", lambda now=None: True)
    now = datetime.now(UTC)
    assert freshness(now)["state"] == "FRESH"
    assert freshness(datetime(2020, 1, 1, tzinfo=UTC))["state"] == "STALE"


def test_market_session_weekday_and_weekend() -> None:
    assert market_open(datetime(2026, 8, 13, 10, tzinfo=UTC))
    assert not market_open(datetime(2026, 8, 15, 10, tzinfo=UTC))


def test_dashboard_aggregates_real_persisted_data(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    db = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(db)
    factory = sessionmaker(bind=db, expire_on_commit=False)
    stamp = datetime.now(UTC)
    features = {
        "signal_id": "s1",
        "symbol": "ASELS",
        "timestamp": stamp.isoformat(),
        "radar_score": 91,
        "classification": "VERY_STRONG_CANDIDATE",
        "price": 100,
        "rvol": 2,
        "early_momentum_score": 80,
        "data_quality": 100,
        "market_regime": "NEUTRAL",
        "daily_trend": "UPTREND",
        "breakout_distance": 0,
        "atr": 2,
        "vwap_distance": 1,
        "ema9_distance": 1,
        "ema20_distance": 1,
        "disposition": "SIGNAL_CREATED",
        "trade_plan_snapshot": {
            "symbol": "ASELS",
            "timestamp": stamp.isoformat(),
            "status": "BREAKOUT_ONAYI",
            "targets": [{"price": 104}, {"price": 106}, {"price": 108}],
            "research_only": True,
        },
    }
    with factory.begin() as session:
        for index in range(25):
            session.add(
                MarketBarRow(
                    symbol="ASELS",
                    timestamp=stamp,
                    open=99,
                    high=101,
                    low=98,
                    close=100,
                    volume=1000,
                    timeframe="15m",
                    provider_id="yfinance-research",
                )
            )
            stamp = stamp.replace(microsecond=index + 1)
        session.add(
            MlFeatureSnapshotRow(
                signal_id="s1",
                symbol="ASELS",
                timeframe="15m",
                signal_time=stamp,
                lifecycle="OUTCOME_PENDING",
                feature_schema_version="v1",
                features=features,
            )
        )
        session.add(WorkerStateRow(job_name="scan", status="HEALTHY", detail={}))
        session.add(
            PaperTradeRow(
                trade_id="t1",
                symbol="ASELS",
                signal_time=stamp,
                entry_time=stamp,
                entry_price=Decimal("100"),
                position_size=Decimal("1"),
                stop_price=Decimal("98"),
                target_1=Decimal("104"),
                target_2=Decimal("106"),
                strategy_id="radar-intraday-v1",
            )
        )
    monkeypatch.setattr(dashboard, "SessionLocal", factory)

    class Reports:
        def latest_report(self, _: str, **__: object):
            return {"data_timestamp": stamp, "candidates": [features]}

    class Intraday:
        def status(self):
            return {"pending": 1}

    monkeypatch.setattr(dashboard, "ResearchRepository", Reports)
    monkeypatch.setattr(dashboard, "IntradayRepository", Intraday)
    assert dashboard.dashboard_summary()["counts"]["VERY_STRONG_CANDIDATE"] == 1
    assert dashboard.candidates()[0]["symbol"] == "ASELS"
    detail = dashboard.symbol_detail("ASELS", 20)
    assert detail and len(detail["bars"]) == 20 and detail["progression"]
    assert detail["trade_plan"]["status"] == "BREAKOUT_ONAYI"
    assert len(detail["trade_plan"]["targets"]) == 3
    assert dashboard.dashboard_trade_plans()[0]["symbol"] == "ASELS"
    opportunities = dashboard.dashboard_opportunities()
    assert opportunities["snapshot_id"]
    opportunity = opportunities["opportunities"][0]
    assert dashboard._candidate_timestamp(opportunity["candidate"]) == datetime.fromisoformat(
        opportunity["plan"]["timestamp"]
    )
    assert dashboard.trade_plan("NONE")["status"] == "GECERSIZ"
    assert dashboard.symbol_detail("NONE") is None
    assert dashboard.signal_history(symbol="ASELS")[0]["lifecycle"] == "OUTCOME_PENDING"
    assert dashboard.performance_summary()["open_positions"] == 1
    assert dashboard.system_overview()["worker_jobs"][0]["status"] == "HEALTHY"


def test_candidates_are_unique_newest_and_deterministically_ranked(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    older = {"symbol": "ASTOR", "radar_score": 99, "timestamp": "2026-08-13T10:00:00+00:00"}
    newest = {"symbol": "astor", "radar_score": 80, "timestamp": "2026-08-13T10:15:00+00:00"}
    same_score = {"symbol": "ASELS", "radar_score": 80, "timestamp": "2026-08-13T10:15:00+00:00"}

    class Reports:
        def latest_report(self, _: str, **__: object):
            return {"candidates": [older, newest, same_score]}

    monkeypatch.setattr(dashboard, "ResearchRepository", Reports)
    rows = dashboard.candidates()
    assert [row["symbol"] for row in rows] == ["ASELS", "ASTOR"]
    assert rows[1]["radar_score"] == 80


def test_candidates_merge_provider_aliases_and_strategies(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    stamp = "2026-08-13T10:15:00+00:00"
    raw = [
        {"symbol": "SELEC.IS", "radar_score": 80, "timestamp": stamp, "strategy_id": "breakout"},
        {"symbol": "selec", "radar_score": 82, "timestamp": stamp, "strategy_id": "momentum"},
    ]

    class Reports:
        def latest_report(self, _: str, **__: object):
            return {"candidates": raw}

    monkeypatch.setattr(dashboard, "ResearchRepository", Reports)
    rows = dashboard.candidates()
    assert len(rows) == 1 and rows[0]["symbol"] == "SELEC"
    assert rows[0]["radar_score"] == 82
    assert rows[0]["matched_strategies"] == ["breakout", "momentum"]


def test_actionable_candidate_ranks_before_higher_waiting_score(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    rows = [
        {
            "symbol": "WAIT",
            "radar_score": 94,
            "timestamp": "2026-08-13T10:15:00+00:00",
            "action_state": "GIRIS_BEKLENIYOR",
        },
        {
            "symbol": "READY",
            "radar_score": 81,
            "timestamp": "2026-08-13T10:15:00+00:00",
            "action_state": "GIRIS_BOLGESINDE",
        },
    ]

    class Reports:
        def latest_report(self, _: str, **__: object):
            return {"candidates": rows}

    monkeypatch.setattr(dashboard, "ResearchRepository", Reports)
    assert [row["symbol"] for row in dashboard.candidates()] == ["READY", "WAIT"]


def test_opportunity_read_uses_persisted_plans_without_financial_recalculation(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    stamp = datetime.now(UTC)
    rows = [
        {
            "symbol": symbol,
            "timestamp": stamp,
            "trade_plan_snapshot": {
                "symbol": symbol,
                "timestamp": stamp,
                "status": "GIRIS_BEKLENIYOR",
                "research_only": True,
            },
        }
        for symbol in ("ASELS", "TUPRS")
    ]
    plans = dashboard._persisted_plans(rows)
    assert set(plans) == {"ASELS", "TUPRS"}
    assert all(plan["status"] == "GIRIS_BEKLENIYOR" for plan in plans.values())


def test_snapshot_status_reads_metadata_without_plan_work(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    stamp = datetime.now(UTC)
    db = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(db)
    factory = sessionmaker(bind=db, expire_on_commit=False)
    with factory.begin() as session:
        session.add(
            WorkerStateRow(
                job_name="intraday_radar_scan",
                status="HEALTHY",
                detail={},
                last_processed_bar=stamp,
                last_success_at=stamp,
            )
        )
    monkeypatch.setattr(dashboard, "SessionLocal", factory)
    status = dashboard.dashboard_snapshot_status()
    assert status["snapshot_id"]
    assert status["data_timestamp"].replace(tzinfo=UTC) == stamp
    assert status["generated_at"].replace(tzinfo=UTC) == stamp


def test_dashboard_performance_excludes_acceptance_context(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    db = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(db)
    factory = sessionmaker(bind=db, expire_on_commit=False)
    stamp = datetime.now(UTC)
    common = dict(
        signal_time=stamp,
        entry_time=stamp,
        entry_price=Decimal("100"),
        position_size=Decimal("1"),
        stop_price=Decimal("98"),
        target_1=Decimal("104"),
        target_2=Decimal("106"),
    )
    with factory.begin() as session:
        session.add(
            PaperTradeRow(
                trade_id="fixture",
                symbol="PERSIST_CLOSED",
                portfolio_id="acceptance-fixture",
                strategy_id="acceptance-test",
                net_return=Decimal("196.7001"),
                **common,
            )
        )
        session.add(
            PaperTradeRow(
                trade_id="real",
                symbol="ASELS",
                portfolio_id="paper-default",
                strategy_id="radar-intraday-v1",
                **common,
            )
        )
    monkeypatch.setattr(dashboard, "SessionLocal", factory)
    result = dashboard.performance_summary()
    assert result["trade_count"] == 1
    assert result["realized_pnl"] == 0

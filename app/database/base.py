from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    DateTime,
    Engine,
    Float,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


class SymbolRow(Base):
    __tablename__ = "symbols"
    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    active: Mapped[bool] = mapped_column(default=True)


class MarketBarRow(Base):
    __tablename__ = "market_bars"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
    __table_args__ = (Index("uq_bar_symbol_time", "symbol", "timestamp", unique=True),)


class EventRow(Base):
    __tablename__ = "system_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event: Mapped[str] = mapped_column(String(80), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    detail: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)


class PaperTradeRow(Base):
    __tablename__ = "paper_trades"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    portfolio_id: Mapped[str] = mapped_column(String(40), default="paper-default")
    strategy_id: Mapped[str] = mapped_column(String(40), default="radar-v1")
    active_symbol: Mapped[str | None] = mapped_column(String(16), nullable=True)
    signal_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    entry_price: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    position_size: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    stop_price: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    target_1: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    target_2: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    exit_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    gross_return: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0"))
    fees: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0"))
    slippage: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0"))
    net_return: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0"))
    __table_args__ = (
        UniqueConstraint(
            "portfolio_id", "strategy_id", "active_symbol", name="uq_paper_trade_scope_active"
        ),
    )


class ReplayRunRow(Base):
    __tablename__ = "replay_runs"
    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_processed_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20))
    config_hash: Mapped[str] = mapped_column(String(64), index=True)
    config_snapshot: Mapped[dict[str, object]] = mapped_column(JSON)
    result: Mapped[dict[str, object]] = mapped_column(JSON)


class ReplayTradeRow(Base):
    __tablename__ = "replay_trades"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    portfolio_id: Mapped[str] = mapped_column(String(40))
    strategy_id: Mapped[str] = mapped_column(String(40))
    symbol: Mapped[str] = mapped_column(String(16))
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class ReplayEquityRow(Base):
    __tablename__ = "replay_equity"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    equity: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    peak_equity: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    drawdown: Mapped[Decimal] = mapped_column(Numeric(20, 8))


class ProviderRow(Base):
    __tablename__ = "providers"
    provider_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    data_mode: Mapped[str] = mapped_column(String(20))
    health: Mapped[str] = mapped_column(String(20))
    capabilities: Mapped[dict[str, object]] = mapped_column(JSON)


class HistoricalDatasetRow(Base):
    __tablename__ = "historical_datasets"
    dataset_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(40), index=True)
    manifest: Mapped[dict[str, object]] = mapped_column(JSON)
    dataset_hash: Mapped[str] = mapped_column(String(64), index=True)


class DataQualityRow(Base):
    __tablename__ = "data_quality_metrics"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(40), index=True)
    day: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    metrics: Mapped[dict[str, object]] = mapped_column(JSON)


class DataRevisionRow(Base):
    __tablename__ = "data_revisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(40), index=True)
    symbol: Mapped[str] = mapped_column(String(16))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    old_value: Mapped[dict[str, object]] = mapped_column(JSON)
    new_value: Mapped[dict[str, object]] = mapped_column(JSON)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class QuarantinedDataRow(Base):
    __tablename__ = "quarantined_market_data"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(40), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, object]] = mapped_column(JSON)
    errors: Mapped[dict[str, object]] = mapped_column(JSON)


def engine() -> Engine:
    return create_engine(get_settings().database_url)


SessionLocal = sessionmaker(bind=engine(), expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine())

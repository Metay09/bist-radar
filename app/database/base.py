from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Engine, Float, Index, Integer, String, create_engine
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


def engine() -> Engine:
    return create_engine(get_settings().database_url)


SessionLocal = sessionmaker(bind=engine())


def init_db() -> None:
    Base.metadata.create_all(engine())

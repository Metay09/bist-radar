from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
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


class UniverseSnapshotRow(Base):
    __tablename__ = "universe_snapshots"
    snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source: Mapped[str] = mapped_column(String(200))
    source_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    instrument_count: Mapped[int] = mapped_column(Integer)
    equity_count: Mapped[int] = mapped_column(Integer)


class UniverseSymbolRow(Base):
    __tablename__ = "universe_symbols"
    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    canonical_symbol: Mapped[str] = mapped_column(String(16), unique=True)
    company_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    market: Mapped[str | None] = mapped_column(String(100), nullable=True)
    instrument_type: Mapped[str] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(String(200))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    active: Mapped[bool] = mapped_column(index=True)
    provider_symbol: Mapped[str | None] = mapped_column(String(24), nullable=True, unique=True)
    provider_status: Mapped[str] = mapped_column(String(40), index=True)
    validation_status: Mapped[str] = mapped_column(String(40), index=True)
    latest_provider_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_probed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UniverseMembershipRow(Base):
    __tablename__ = "universe_memberships"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    market: Mapped[str | None] = mapped_column(String(100), nullable=True)
    active: Mapped[bool] = mapped_column(default=True)
    event: Mapped[str] = mapped_column(String(30))
    __table_args__ = (
        UniqueConstraint("snapshot_id", "symbol", name="uq_universe_snapshot_symbol"),
    )


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
    timeframe: Mapped[str | None] = mapped_column(String(8), nullable=True)
    provider_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    dataset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_adjusted: Mapped[bool | None] = mapped_column(nullable=True)
    adjustment_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    quality_flags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    __table_args__ = (
        Index(
            "uq_bar_provider_symbol_tf_time",
            "provider_id",
            "symbol",
            "timeframe",
            "timestamp",
            unique=True,
        ),
    )


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


class ResearchReportRow(Base):
    __tablename__ = "research_reports"
    report_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    report_type: Mapped[str] = mapped_column(String(20), index=True)
    dataset_id: Mapped[str] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class MlFeatureSnapshotRow(Base):
    __tablename__ = "ml_feature_snapshots"
    signal_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    timeframe: Mapped[str] = mapped_column(String(8))
    signal_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    lifecycle: Mapped[str] = mapped_column(String(24), default="OUTCOME_PENDING")
    feature_schema_version: Mapped[str] = mapped_column(String(30))
    features: Mapped[dict[str, object]] = mapped_column(JSON)


class MlOutcomeRow(Base):
    __tablename__ = "ml_outcomes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_id: Mapped[str] = mapped_column(String(120), index=True)
    horizon: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24))
    outcome: Mapped[dict[str, object]] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("signal_id", "horizon", name="uq_ml_outcome_horizon"),)


class SignalAuditRow(Base):
    """Monotonic, persisted level truth derived only from completed future bars."""

    __tablename__ = "signal_audits"
    signal_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    audit_version: Mapped[int] = mapped_column(Integer, default=2)
    entry_hit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    entry_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    stop_hit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    target1_hit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    target2_hit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    target3_hit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ordering: Mapped[str] = mapped_column(String(24), default="NONE")
    result_classification: Mapped[str] = mapped_column(String(32), default="PENDING")
    highest_target: Mapped[int] = mapped_column(Integer, default=0)
    bars_to_entry: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bars_after_entry: Mapped[int] = mapped_column(Integer, default=0)
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AdaptiveSetupRow(Base):
    __tablename__ = "adaptive_setups"
    setup_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    signal_id: Mapped[str] = mapped_column(String(120), index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    policy_version: Mapped[str] = mapped_column(String(40), index=True)
    state: Mapped[str] = mapped_column(String(40), index=True)
    health: Mapped[str] = mapped_column(String(24))
    current_plan_version: Mapped[int] = mapped_column(Integer, default=1)
    signal_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    entry_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    entry_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    initial_stop: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    active_stop: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    exit_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    highest_target: Mapped[int] = mapped_column(Integer, default=0)
    action: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    config: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AdaptivePlanVersionRow(Base):
    __tablename__ = "adaptive_plan_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    setup_id: Mapped[str] = mapped_column(String(160), index=True)
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(String(80))
    plan: Mapped[dict[str, object]] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("setup_id", "version", name="uq_adaptive_plan_version"),)


class AdaptiveEventRow(Base):
    __tablename__ = "adaptive_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    setup_id: Mapped[str] = mapped_column(String(160), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    state_from: Mapped[str | None] = mapped_column(String(40), nullable=True)
    state_to: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("setup_id", "sequence", name="uq_adaptive_event_seq"),)


class MlDatasetRow(Base):
    __tablename__ = "ml_datasets"
    dataset_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, object]] = mapped_column("metadata", JSON)


class MlModelRow(Base):
    __tablename__ = "ml_models"
    model_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    model_type: Mapped[str] = mapped_column(String(40))
    metadata_json: Mapped[dict[str, object]] = mapped_column("metadata", JSON)


class MlPredictionRow(Base):
    __tablename__ = "ml_predictions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_id: Mapped[str] = mapped_column(String(120), index=True)
    model_id: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    predictions: Mapped[dict[str, object]] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("signal_id", "model_id", name="uq_ml_prediction"),)


class MlEvaluationRow(Base):
    __tablename__ = "ml_evaluations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[str] = mapped_column(String(80), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    metrics: Mapped[dict[str, object]] = mapped_column(JSON)


class ResearchBaselineRow(Base):
    __tablename__ = "research_baselines"
    baseline_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    immutable: Mapped[bool] = mapped_column(Boolean, default=True)
    manifest: Mapped[dict[str, object]] = mapped_column(JSON)


class FeatureDefinitionRow(Base):
    __tablename__ = "feature_definitions"
    name: Mapped[str] = mapped_column(String(80), primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(40), index=True)
    source_timeframe: Mapped[str] = mapped_column(String(16))
    formula: Mapped[str] = mapped_column(String(500))
    missing_policy: Mapped[str] = mapped_column(String(80))
    metadata_json: Mapped[dict[str, object]] = mapped_column("metadata", JSON)


class FeatureObservationRow(Base):
    __tablename__ = "feature_observations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_id: Mapped[str] = mapped_column(String(120), index=True)
    feature_name: Mapped[str] = mapped_column(String(80), index=True)
    source_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    availability_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    value_json: Mapped[dict[str, object]] = mapped_column("value", JSON)
    __table_args__ = (UniqueConstraint("signal_id", "feature_name", name="uq_feature_observation"),)


class DataFreshnessObservationRow(Base):
    __tablename__ = "data_freshness_observations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(40), index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    timeframe: Mapped[str] = mapped_column(String(8))
    bar_close_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    provider_available_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    persist_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, object]] = mapped_column("metadata", JSON)
    __table_args__ = (
        UniqueConstraint(
            "provider_id", "symbol", "timeframe", "bar_close_time", name="uq_freshness_bar"
        ),
    )


class MlExperimentRow(Base):
    __tablename__ = "ml_experiments"
    experiment_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    data_hash: Mapped[str] = mapped_column(String(64), index=True)
    feature_schema: Mapped[str] = mapped_column(String(40))
    policy_version: Mapped[str] = mapped_column(String(40), index=True)
    model: Mapped[str] = mapped_column(String(80))
    hyperparameters: Mapped[dict[str, object]] = mapped_column(JSON)
    date_ranges: Mapped[dict[str, object]] = mapped_column(JSON)
    prior_trials: Mapped[int] = mapped_column(Integer)
    metrics: Mapped[dict[str, object]] = mapped_column(JSON)


class ResearchCycleRow(Base):
    __tablename__ = "research_cycles"
    cycle_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    completed_bar_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), index=True)
    checkpoints: Mapped[dict[str, object]] = mapped_column(JSON)
    metrics: Mapped[dict[str, object]] = mapped_column(JSON)


class ResearchLabelRow(Base):
    __tablename__ = "research_labels"
    signal_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    policy_version: Mapped[str] = mapped_column(String(40), index=True)
    terminal_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cost_adjusted_r: Mapped[float | None] = mapped_column(Float, nullable=True)
    labels: Mapped[dict[str, object]] = mapped_column(JSON)
    trace: Mapped[dict[str, object]] = mapped_column(JSON)


class ResearchDatasetVersionRow(Base):
    __tablename__ = "research_dataset_versions"
    dataset_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    data_hash: Mapped[str] = mapped_column(String(64), index=True)
    label_count: Mapped[int] = mapped_column(Integer)
    feature_schema: Mapped[str] = mapped_column(String(40))
    policy_version: Mapped[str] = mapped_column(String(40))
    manifest: Mapped[dict[str, object]] = mapped_column(JSON)


class DailyResearchSnapshotRow(Base):
    __tablename__ = "daily_research_snapshots"
    session_date: Mapped[str] = mapped_column(String(10), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    metrics: Mapped[dict[str, object]] = mapped_column(JSON)
    deltas: Mapped[dict[str, object]] = mapped_column(JSON)


class WeeklyResearchReportRow(Base):
    __tablename__ = "weekly_research_reports"
    week_start: Mapped[str] = mapped_column(String(10), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class NotificationEventRow(Base):
    __tablename__ = "notification_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dedup_key: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    alert_type: Mapped[str] = mapped_column(String(40), index=True)
    symbol: Mapped[str | None] = mapped_column(String(16), nullable=True)
    signal_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkerStateRow(Base):
    __tablename__ = "worker_state"
    job_name: Mapped[str] = mapped_column(String(80), primary_key=True)
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_processed_bar: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(30), default="UNKNOWN")
    detail: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)


def engine() -> Engine:
    return create_engine(get_settings().database_url)


SessionLocal = sessionmaker(bind=engine(), expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine())

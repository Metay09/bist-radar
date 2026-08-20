from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from app.market.bist import TickDirection, canonical_bist_symbol, round_to_tick


class Timeframe(StrEnum):
    D1 = "1d"
    M60 = "60m"
    M30 = "30m"
    M15 = "15m"
    M5 = "5m"


class ExecutionState(StrEnum):
    SIGNAL_CREATED = "SIGNAL_CREATED"
    PENDING_ENTRY = "PENDING_ENTRY"
    OPEN = "OPEN"
    PARTIALLY_EXITED = "PARTIALLY_EXITED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


TRANSITIONS = {
    ExecutionState.SIGNAL_CREATED: {
        ExecutionState.PENDING_ENTRY,
        ExecutionState.REJECTED,
        ExecutionState.CANCELLED,
    },
    ExecutionState.PENDING_ENTRY: {
        ExecutionState.OPEN,
        ExecutionState.REJECTED,
        ExecutionState.CANCELLED,
    },
    ExecutionState.OPEN: {ExecutionState.PARTIALLY_EXITED, ExecutionState.CLOSED},
    ExecutionState.PARTIALLY_EXITED: {ExecutionState.CLOSED},
    ExecutionState.CLOSED: set(),
    ExecutionState.CANCELLED: set(),
    ExecutionState.REJECTED: set(),
}


@dataclass
class ExecutionOrder:
    signal_id: str
    idempotency_key: str
    portfolio_id: str
    strategy_id: str
    symbol: str
    signal_time: datetime
    expected_entry: Decimal
    stop: Decimal
    target_1: Decimal
    target_2: Decimal
    score: int
    data_quality: int
    state: ExecutionState = ExecutionState.SIGNAL_CREATED
    rejection_reason: str | None = None

    def __post_init__(self) -> None:
        self.symbol = canonical_bist_symbol(self.symbol)
        self.expected_entry = round_to_tick(self.expected_entry, TickDirection.CEIL)
        self.stop = round_to_tick(self.stop, TickDirection.FLOOR)
        self.target_1 = round_to_tick(self.target_1, TickDirection.FLOOR)
        self.target_2 = round_to_tick(self.target_2, TickDirection.FLOOR)
        if not self.stop < self.expected_entry < self.target_1 < self.target_2:
            raise ValueError("tick normalization produced invalid execution order")

    def transition(self, target: ExecutionState) -> None:
        if target not in TRANSITIONS[self.state]:
            raise ValueError(f"invalid transition {self.state}->{target}")
        self.state = target


@dataclass
class ExecutedTrade:
    signal_id: str
    trade_id: str
    idempotency_key: str
    portfolio_id: str
    strategy_id: str
    symbol: str
    signal_time: datetime
    entry_time: datetime
    entry_price: Decimal
    stop: Decimal
    target_1: Decimal
    target_2: Decimal
    quantity: Decimal
    equity_before: Decimal
    execution_model: str
    state: ExecutionState = ExecutionState.OPEN
    exit_time: datetime | None = None
    exit_price: Decimal | None = None
    exit_reason: str | None = None
    gross_pnl: Decimal = Decimal("0")
    commission: Decimal = Decimal("0")
    slippage: Decimal = Decimal("0")
    net_pnl: Decimal = Decimal("0")
    equity_after: Decimal | None = None
    initial_risk: Decimal = Decimal("0")


@dataclass(frozen=True)
class EquityPoint:
    timestamp: datetime
    equity: Decimal
    peak_equity: Decimal
    drawdown: Decimal


@dataclass
class ReplayResult:
    run_id: str
    initial_equity: Decimal
    final_equity: Decimal
    trades: list[ExecutedTrade] = field(default_factory=list)
    audits: list[dict[str, str]] = field(default_factory=list)
    equity_curve: list[EquityPoint] = field(default_factory=list)
    config_hash: str = ""
    last_processed_timestamp: datetime | None = None

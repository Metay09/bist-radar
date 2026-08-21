from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import uuid4

from app.backtest.replay_models import ExecutedTrade, ExecutionOrder, ExecutionState
from app.market.bist import TickDirection, round_to_tick
from app.risk.engine import position_size

D = Decimal


class IntrabarPolicy(StrEnum):
    STOP_FIRST = "STOP_FIRST"


@dataclass(frozen=True)
class ExecutionConfig:
    max_entry_gap_percent: Decimal = D("3")
    max_open_positions: int = 5
    max_total_open_risk_percent: Decimal = D("3")
    max_position_percent: Decimal = D("20")
    risk_percent: Decimal = D("0.75")
    commission_bps: Decimal = D("10")
    slippage_bps: Decimal = D("5")
    ambiguity_policy: IntrabarPolicy = IntrabarPolicy.STOP_FIRST
    reject_corporate_actions: bool = True


class PaperExecutionEngine:
    def __init__(self, config: ExecutionConfig) -> None:
        self.config = config

    def enter(
        self,
        order: ExecutionOrder,
        timestamp: datetime,
        open_price: Decimal,
        equity: Decimal,
        open_trades: list[ExecutedTrade],
    ) -> ExecutedTrade | None:
        gap = abs(open_price / order.expected_entry - 1) * 100
        if gap > self.config.max_entry_gap_percent:
            order.transition(ExecutionState.REJECTED)
            order.rejection_reason = "REJECTED_ENTRY_GAP"
            return None
        if len(open_trades) >= self.config.max_open_positions:
            order.transition(ExecutionState.REJECTED)
            order.rejection_reason = "REJECTED_PORTFOLIO_RISK"
            return None
        current_risk = sum(t.initial_risk for t in open_trades)
        budget = equity * self.config.max_total_open_risk_percent / 100
        quantity = position_size(
            equity,
            open_price,
            order.stop,
            self.config.risk_percent,
            self.config.max_position_percent,
        )
        planned_risk = quantity * (open_price - order.stop)
        if quantity <= 0 or current_risk + planned_risk > budget:
            order.transition(ExecutionState.REJECTED)
            order.rejection_reason = "REJECTED_PORTFOLIO_RISK"
            return None
        fill = round_to_tick(
            open_price * (1 + self.config.slippage_bps / D("10000")), TickDirection.CEIL
        )
        order.transition(ExecutionState.OPEN)
        return ExecutedTrade(
            order.signal_id,
            str(uuid4()),
            order.idempotency_key,
            order.portfolio_id,
            order.strategy_id,
            order.symbol,
            order.signal_time,
            timestamp,
            fill,
            order.stop,
            order.target_1,
            order.target_2,
            quantity,
            equity,
            "NEXT_BAR_OPEN",
            initial_risk=quantity * (fill - order.stop),
            slippage=(fill - open_price) * quantity,
        )

    def evaluate_exit(
        self,
        trade: ExecutedTrade,
        timestamp: datetime,
        open_price: Decimal,
        high: Decimal,
        low: Decimal,
        equity: Decimal,
    ) -> Decimal:
        if trade.state != ExecutionState.OPEN:
            return equity
        reason: str | None = None
        raw_fill: Decimal | None = None
        if open_price <= trade.stop:
            reason, raw_fill = "STOP_GAP", open_price
        elif open_price >= trade.target_2:
            reason, raw_fill = "TARGET_2_GAP", open_price
        elif low <= trade.stop and high >= trade.target_1:
            reason, raw_fill = "STOP_FIRST_AMBIGUITY", trade.stop
        elif low <= trade.stop:
            reason, raw_fill = "STOP", trade.stop
        elif high >= trade.target_2:
            reason, raw_fill = "TARGET_2", trade.target_2
        elif high >= trade.target_1:
            reason, raw_fill = "TARGET_1", trade.target_1
        if raw_fill is None:
            return equity
        fill = round_to_tick(
            raw_fill * (1 - self.config.slippage_bps / D("10000")), TickDirection.FLOOR
        )
        trade.exit_time, trade.exit_price, trade.exit_reason = timestamp, fill, reason
        trade.gross_pnl = (fill - trade.entry_price) * trade.quantity
        trade.commission = (
            (trade.entry_price + fill) * trade.quantity * self.config.commission_bps / D("10000")
        )
        trade.slippage += (raw_fill - fill) * trade.quantity
        trade.net_pnl = trade.gross_pnl - trade.commission
        trade.equity_after = equity + trade.net_pnl
        trade.state = ExecutionState.CLOSED
        return trade.equity_after

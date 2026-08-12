import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pandas as pd

from app.backtest.metrics import calculate_metrics
from app.backtest.replay_models import (
    EquityPoint,
    ExecutedTrade,
    ExecutionOrder,
    ExecutionState,
    ReplayResult,
    Timeframe,
)
from app.core.clock import ReplayClock
from app.data.historical import HistoricalProvider, SymbolMetadata
from app.paper.execution import ExecutionConfig, PaperExecutionEngine

SignalStrategy = Callable[[str, pd.DataFrame], ExecutionOrder | None]


def stable_config_hash(config: ExecutionConfig) -> str:
    payload = {key: str(value) for key, value in vars(config).items()}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def possible_corporate_action(
    previous_close: Decimal, current_open: Decimal, threshold: Decimal = Decimal("25")
) -> bool:
    return abs(current_open / previous_close - 1) * 100 > threshold


class HistoricalReplayEngine:
    def __init__(
        self,
        provider: HistoricalProvider,
        symbols: dict[str, SymbolMetadata],
        strategy: SignalStrategy,
        config: ExecutionConfig | None = None,
    ) -> None:
        config = config or ExecutionConfig()
        self.provider, self.symbols, self.strategy, self.config = (
            provider,
            symbols,
            strategy,
            config,
        )
        self.execution = PaperExecutionEngine(config)

    def run(
        self,
        symbols: list[str],
        timeframe: Timeframe,
        start: datetime | None,
        end: datetime | None,
        initial_equity: Decimal,
        run_id: str | None = None,
    ) -> ReplayResult:
        if initial_equity <= 0:
            raise ValueError("initial equity must be positive")
        if any(s not in self.symbols or not self.symbols[s].active for s in symbols):
            raise ValueError("unknown symbol")
        frames = {s: self.provider.load(s, timeframe, start, end) for s in symbols}
        timeline = sorted(set().union(*(set(f.timestamp) for f in frames.values())))
        positions = {
            symbol: {stamp: index for index, stamp in enumerate(frame.timestamp)}
            for symbol, frame in frames.items()
        }
        result = ReplayResult(
            run_id or str(uuid4()),
            initial_equity,
            initial_equity,
            config_hash=stable_config_hash(self.config),
        )
        if not timeline:
            return result
        clock = ReplayClock(timeline[0].to_pydatetime())
        pending: dict[str, ExecutionOrder] = {}
        seen: set[str] = set()
        open_trades: list[ExecutedTrade] = []
        equity = initial_equity
        peak = initial_equity
        for stamp in timeline:
            now = stamp.to_pydatetime()
            clock.advance(now)
            result.last_processed_timestamp = now
            current_bars: dict[str, Any] = {}
            visible_frames: dict[str, pd.DataFrame] = {}
            for symbol, frame in frames.items():
                position = positions[symbol].get(stamp)
                if position is None:
                    continue
                visible = frame.iloc[: position + 1]
                visible_frames[symbol] = visible
                bar = visible.iloc[-1]
                current_bars[symbol] = bar
                op, hi, lo = map(lambda x: Decimal(str(x)), (bar.open, bar.high, bar.low))
                for trade in list(open_trades):
                    if trade.symbol == symbol:
                        new_equity = self.execution.evaluate_exit(trade, now, op, hi, lo, equity)
                        if new_equity != equity:
                            equity = new_equity
                            peak = max(peak, equity)
                            result.equity_curve.append(
                                EquityPoint(now, equity, peak, equity / peak - 1)
                            )
                            open_trades.remove(trade)
            eligible = [pending.pop(symbol) for symbol in current_bars if symbol in pending]
            eligible.sort(
                key=lambda order: (
                    -order.score,
                    -order.data_quality,
                    -float(
                        (order.target_2 - order.expected_entry)
                        / (order.expected_entry - order.stop)
                    ),
                    order.symbol,
                )
            )
            for order in eligible:
                symbol = order.symbol
                visible = visible_frames[symbol]
                bar = current_bars[symbol]
                op = Decimal(str(bar.open))
                if order:
                    if (
                        len(visible) > 1
                        and possible_corporate_action(Decimal(str(visible.iloc[-2].close)), op)
                        and self.config.reject_corporate_actions
                    ):
                        order.transition(ExecutionState.REJECTED)
                        order.rejection_reason = "REJECTED_CORPORATE_ACTION"
                        result.audits.append(
                            {"signal_id": order.signal_id, "result": order.rejection_reason}
                        )
                    else:
                        entered = self.execution.enter(order, now, op, equity, open_trades)
                        result.audits.append(
                            {
                                "signal_id": order.signal_id,
                                "result": "TRADE_OPENED"
                                if entered
                                else str(order.rejection_reason),
                            }
                        )
                        if entered:
                            result.trades.append(entered)
                            open_trades.append(entered)
            for symbol in current_bars:
                visible = visible_frames[symbol]
                signal = self.strategy(symbol, visible.copy())
                if signal:
                    if (
                        signal.idempotency_key in seen
                        or symbol in pending
                        or any(t.symbol == symbol for t in open_trades)
                    ):
                        result.audits.append(
                            {"signal_id": signal.signal_id, "result": "REJECTED_DUPLICATE"}
                        )
                    elif signal.score < 80:
                        result.audits.append(
                            {"signal_id": signal.signal_id, "result": "REJECTED_LOW_SCORE"}
                        )
                    elif signal.data_quality < 90:
                        result.audits.append(
                            {"signal_id": signal.signal_id, "result": "REJECTED_LOW_DATA_QUALITY"}
                        )
                    else:
                        signal.transition(ExecutionState.PENDING_ENTRY)
                        pending[symbol] = signal
                        seen.add(signal.idempotency_key)
        result.final_equity = equity
        return result


def replay_performance(result: ReplayResult) -> dict[str, float | int]:
    closed = [t for t in result.trades if t.state == ExecutionState.CLOSED]
    returns = [float(t.net_pnl / t.equity_before) for t in closed]
    durations = [
        (t.exit_time - t.entry_time).total_seconds() / 86400 for t in closed if t.exit_time
    ]
    base = calculate_metrics(returns, durations)
    r_values = [float(t.net_pnl / t.initial_risk) for t in closed if t.initial_risk > 0]
    exposure = (
        sum(durations)
        / max(1, (result.last_processed_timestamp - closed[0].signal_time).total_seconds() / 86400)
        * 100
        if closed and result.last_processed_timestamp
        else 0
    )
    return {
        **vars(base),
        "profit_factor_is_infinite": base.profit_factor == float("inf"),
        "initial_equity": float(result.initial_equity),
        "final_equity": float(result.final_equity),
        "net_pnl": float(result.final_equity - result.initial_equity),
        "exposure_percent": exposure,
        "average_R": sum(r_values) / len(r_values) if r_values else 0,
        "median_R": sorted(r_values)[len(r_values) // 2] if r_values else 0,
    }


def daily_analytics(
    result: ReplayResult, sectors: dict[str, str] | None = None
) -> list[dict[str, object]]:
    sectors = sectors or {}
    return [
        {
            "date": trade.exit_time.date().isoformat(),
            "weekday": trade.exit_time.strftime("%A"),
            "hour": trade.exit_time.hour,
            "symbol": trade.symbol,
            "sector": sectors.get(trade.symbol),
            "net_pnl": float(trade.net_pnl),
        }
        for trade in result.trades
        if trade.exit_time
    ]

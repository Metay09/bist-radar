from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Any

import pandas as pd

from app.backtest.replay import HistoricalReplayEngine, replay_performance
from app.backtest.replay_models import ExecutionOrder, ReplayResult, Timeframe
from app.data.historical import HistoricalProvider, SymbolMetadata
from app.market.analysis import (
    MarketRegime,
    classify_regime,
    classify_trend,
    feature_table,
    features,
    relative_strength,
)
from app.models.domain import DataStatus
from app.paper.execution import ExecutionConfig
from app.risk.engine import build_trade_plan
from app.scoring.radar import RadarResult, score_radar


class FrameHistoricalProvider(HistoricalProvider):
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self.frames = frames

    def load(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        frame = self.frames[symbol]
        if start:
            frame = frame[frame.timestamp >= start]
        if end:
            frame = frame[frame.timestamp <= end]
        return frame.reset_index(drop=True)


def canonical_frames(bars: list[Any]) -> dict[str, pd.DataFrame]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for bar in bars:
        grouped[bar.symbol].append(
            {
                "symbol": bar.symbol,
                "timestamp": bar.timestamp,
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": float(bar.volume),
            }
        )
    return {
        symbol: pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)
        for symbol, rows in grouped.items()
    }


class FrozenRadarStrategy:
    """Radar V1 without optimization; benchmark visibility is capped at signal time."""

    def __init__(self, benchmark: pd.DataFrame, min_warmup_bars: int = 200) -> None:
        self.benchmark = benchmark
        self.min_warmup_bars = min_warmup_bars
        self.latest: dict[str, RadarResult] = {}
        self.rejections: Counter[str] = Counter()
        self.signal_regimes: dict[str, str] = {}
        self.prepared: dict[tuple[str, pd.Timestamp], ExecutionOrder | None] = {}

    def prepare(self, frames: dict[str, pd.DataFrame]) -> None:
        benchmark_features = feature_table(self.benchmark)
        benchmark_regimes: dict[pd.Timestamp, MarketRegime] = {}
        for index in range(self.min_warmup_bars - 1, len(self.benchmark)):
            row = benchmark_features.iloc[index].to_dict()
            benchmark_regimes[pd.Timestamp(self.benchmark.iloc[index].timestamp)] = (
                classify_regime(self.benchmark.iloc[: index + 1])
                if index == self.min_warmup_bars - 1
                else self._regime(row)
            )
        benchmark_returns = self.benchmark.set_index("timestamp").close.pct_change(20)
        for symbol, frame in frames.items():
            table = feature_table(frame)
            stock_returns = frame.set_index("timestamp").close.pct_change(20)
            for index in range(len(frame)):
                timestamp = pd.Timestamp(frame.iloc[index].timestamp)
                key = (symbol, timestamp)
                if index + 1 < self.min_warmup_bars:
                    self.prepared[key] = None
                    continue
                regime = benchmark_regimes.get(timestamp)
                benchmark_return = benchmark_returns.get(timestamp)
                if regime is None or pd.isna(benchmark_return):
                    self.prepared[key] = None
                    continue
                row = table.iloc[index].to_dict()
                self.prepared[key] = self._order(
                    symbol,
                    timestamp,
                    row,
                    regime,
                    float(stock_returns.get(timestamp, float("nan")) - benchmark_return) * 100,
                    frame.iloc[index],
                )

    @staticmethod
    def _regime(f: dict[str, object]) -> MarketRegime:
        trend = classify_trend(f)  # type: ignore[arg-type]
        rsi_value = float(str(f["rsi"]))
        if trend.value in {"STRONG_UPTREND", "UPTREND"} and rsi_value >= 50:
            return MarketRegime.RISK_ON
        if trend.value in {"STRONG_DOWNTREND", "DOWNTREND"} and rsi_value < 45:
            return MarketRegime.RISK_OFF
        return MarketRegime.NEUTRAL

    def _order(
        self,
        symbol: str,
        timestamp: pd.Timestamp,
        f: dict[str, object],
        regime: MarketRegime,
        strength: float,
        bar: Any,
    ) -> ExecutionOrder | None:
        typed_features = {key: value for key, value in f.items()}
        try:
            plan = build_trade_plan(
                Decimal(str(bar.close)),
                Decimal(str(f["atr"])),
                Decimal(str(f["recent_low"])),
            )
        except ValueError:
            return None
        result = score_radar(
            symbol,
            typed_features,  # type: ignore[arg-type]
            classify_trend(typed_features),  # type: ignore[arg-type]
            regime,
            strength,
            float(plan.risk_reward),
            DataStatus.OK,
            100,
        )
        self.latest[symbol] = result
        if result.score < 80:
            return None
        stamp = timestamp.to_pydatetime()
        signal_id = f"{symbol}-{stamp.isoformat()}"
        self.signal_regimes[signal_id] = regime.value
        return ExecutionOrder(
            signal_id,
            f"radar-v1-frozen:{symbol}:{stamp.isoformat()}",
            "paper-default",
            "radar-v1-frozen",
            symbol,
            stamp,
            plan.entry,
            plan.stop,
            plan.target_1,
            plan.target_2,
            result.score,
            100,
        )

    def __call__(self, symbol: str, visible: pd.DataFrame) -> ExecutionOrder | None:
        prepared_key = (symbol, pd.Timestamp(visible.iloc[-1].timestamp))
        if self.prepared:
            prepared_order = self.prepared.get(prepared_key)
            if prepared_order is None:
                reason = "WARMUP_INCOMPLETE" if len(visible) < self.min_warmup_bars else "LOW_SCORE"
                self.rejections[reason] += 1
            return prepared_order
        if len(visible) < self.min_warmup_bars:
            self.rejections["WARMUP_INCOMPLETE"] += 1
            return None
        timestamp = visible.iloc[-1].timestamp
        index_visible = self.benchmark[self.benchmark.timestamp <= timestamp]
        if len(index_visible) < self.min_warmup_bars:
            self.rejections["MISSING_INDEX"] += 1
            return None
        window = visible.tail(max(self.min_warmup_bars, 260))
        index_window = index_visible.tail(max(self.min_warmup_bars, 260))
        f = features(window)
        try:
            plan = build_trade_plan(
                Decimal(str(window.close.iloc[-1])),
                Decimal(str(f["atr"])),
                Decimal(str(f["recent_low"])),
            )
        except ValueError:
            self.rejections["RISK_REWARD"] += 1
            return None
        regime = classify_regime(index_window)
        radar_result = score_radar(
            symbol,
            f,
            classify_trend(f),
            regime,
            relative_strength(window, index_window),
            float(plan.risk_reward),
            DataStatus.OK,
            100,
        )
        self.latest[symbol] = radar_result
        if radar_result.score < 80:
            self.rejections["LOW_SCORE"] += 1
            return None
        stamp = timestamp.to_pydatetime()
        signal_id = f"{symbol}-{stamp.isoformat()}"
        self.signal_regimes[signal_id] = regime.value
        return ExecutionOrder(
            signal_id,
            f"radar-v1-frozen:{symbol}:{stamp.isoformat()}",
            "paper-default",
            "radar-v1-frozen",
            symbol,
            stamp,
            plan.entry,
            plan.stop,
            plan.target_1,
            plan.target_2,
            radar_result.score,
            100,
        )


def run_research_replay(
    bars: list[Any], initial_equity: Decimal, min_warmup_bars: int = 200
) -> tuple[ReplayResult, dict[str, object]]:
    frames = canonical_frames(bars)
    benchmark = frames.pop("XU100", None)
    if benchmark is None:
        raise ValueError("INDEX_DATA_UNAVAILABLE")
    strategy = FrozenRadarStrategy(benchmark, min_warmup_bars)
    strategy.prepare(frames)
    metadata = {symbol: SymbolMetadata(symbol) for symbol in frames}
    config = ExecutionConfig()
    result = HistoricalReplayEngine(
        FrameHistoricalProvider(frames), metadata, strategy, config
    ).run(sorted(frames), Timeframe.D1, None, None, initial_equity)
    performance = replay_performance(result)
    audit_counts = Counter(item["result"] for item in result.audits)
    closed = [trade for trade in result.trades if trade.exit_time]

    def grouped_summary(trades: list[Any]) -> dict[str, object]:
        wins = [trade for trade in trades if trade.net_pnl > 0]
        gains = sum((trade.net_pnl for trade in wins), Decimal("0"))
        losses = -sum((trade.net_pnl for trade in trades if trade.net_pnl < 0), Decimal("0"))
        return {
            "trades": len(trades),
            "net_pnl": float(sum((trade.net_pnl for trade in trades), Decimal("0"))),
            "win_rate": len(wins) / len(trades) * 100 if trades else 0,
            "profit_factor": float(gains / losses) if losses else (None if gains else 0),
        }

    yearly_groups: dict[str, list[Any]] = defaultdict(list)
    symbol_groups: dict[str, list[Any]] = defaultdict(list)
    regime_groups: dict[str, list[Any]] = defaultdict(list)
    for trade in closed:
        assert trade.exit_time is not None
        yearly_groups[str(trade.exit_time.year)].append(trade)
        symbol_groups[trade.symbol].append(trade)
        regime_groups[strategy.signal_regimes.get(trade.signal_id, "UNKNOWN")].append(trade)
    ranked_trades = sorted(closed, key=lambda trade: (trade.net_pnl, trade.trade_id))
    report: dict[str, object] = {
        "strategy_id": "radar-v1-frozen",
        "flags": ["RESEARCH_ONLY", "UNVERIFIED_SOURCE", "ASSUMED_COST_MODEL"],
        "symbols": len(frames),
        "bars": sum(len(frame) for frame in frames.values()) + len(benchmark),
        "signals": len(result.audits),
        "trades": len(result.trades),
        "performance": performance,
        "rejections": dict(strategy.rejections | audit_counts),
        "costs": {"commission_bps": "10", "slippage_bps": "5"},
        "market_regimes": {
            key: grouped_summary(value) for key, value in sorted(regime_groups.items())
        },
        "yearly": {key: grouped_summary(value) for key, value in sorted(yearly_groups.items())},
        "symbols_detail": {
            key: grouped_summary(value) for key, value in sorted(symbol_groups.items())
        },
        "best_trades": [
            {"symbol": trade.symbol, "net_pnl": float(trade.net_pnl)}
            for trade in reversed(ranked_trades[-10:])
        ],
        "worst_trades": [
            {"symbol": trade.symbol, "net_pnl": float(trade.net_pnl)}
            for trade in ranked_trades[:10]
        ],
    }
    return result, report


def research_scan(bars: list[Any], min_warmup_bars: int = 200) -> dict[str, object]:
    frames = canonical_frames(bars)
    benchmark = frames.pop("XU100", None)
    if benchmark is None:
        raise ValueError("INDEX_DATA_UNAVAILABLE")
    strategy = FrozenRadarStrategy(benchmark, min_warmup_bars)
    for symbol in sorted(frames):
        strategy(symbol, frames[symbol])
    candidates = sorted(
        (
            {
                "symbol": item.symbol,
                "score": item.score,
                "classification": item.signal_class.value,
                "data_quality": item.data_quality,
                "reason": item.reasons,
                "data_timestamp": frames[item.symbol].timestamp.iloc[-1].isoformat(),
            }
            for item in strategy.latest.values()
            if item.score >= 70
        ),
        key=lambda item: (-int(item["score"]), str(item["symbol"])),
    )
    return {
        "warning": "RESEARCH DATA - NOT REALTIME - NOT INVESTMENT ADVICE",
        "flags": [
            "RESEARCH_ONLY",
            "UNVERIFIED_SOURCE",
            "SURVIVORSHIP_BIAS_POSSIBLE",
        ],
        "candidates": candidates[:10],
        "rejections": dict(strategy.rejections),
    }

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal

import numpy as np
import pandas as pd

from app.backtest.replay_models import ExecutionState, ReplayResult


@dataclass(frozen=True)
class DailyEquity:
    timestamp: datetime
    realized_equity: float
    mtm_equity: float
    unrealized_pnl: float
    drawdown: float
    gross_exposure: float
    gross_exposure_percent: float
    open_positions: int


def _years(start: datetime, end: datetime) -> float:
    return max((end - start).total_seconds() / (365.2425 * 86400), 1 / 365.2425)


def _cagr(total_return: float, years: float) -> float:
    return (1 + total_return) ** (1 / years) - 1 if total_return > -1 else -1.0


def daily_risk_metrics(equities: list[float], annualization_factor: int = 252) -> dict[str, float]:
    if len(equities) < 2:
        return {"max_drawdown": 0.0, "sharpe_ratio": 0.0, "sortino_ratio": 0.0}
    values = np.asarray(equities, dtype=float)
    returns = values[1:] / values[:-1] - 1
    peaks = np.maximum.accumulate(values)
    drawdowns = values / peaks - 1
    std = returns.std(ddof=1) if len(returns) > 1 else 0.0
    downside = np.minimum(returns, 0)
    downside_deviation = float(np.sqrt(np.mean(downside**2)))
    mean = float(returns.mean())
    return {
        "max_drawdown": float(drawdowns.min()),
        "sharpe_ratio": mean / std * np.sqrt(annualization_factor) if std else 0.0,
        "sortino_ratio": mean / downside_deviation * np.sqrt(annualization_factor)
        if downside_deviation
        else 0.0,
    }


def portfolio_equity_curve(
    result: ReplayResult,
    frames: dict[str, pd.DataFrame],
    timeline: list[datetime],
    commission_bps: Decimal,
    slippage_bps: Decimal,
) -> list[DailyEquity]:
    closes = {
        symbol: frame.set_index("timestamp").close.sort_index() for symbol, frame in frames.items()
    }
    last_prices: dict[str, Decimal] = {}
    curve: list[DailyEquity] = []
    peak = result.initial_equity
    for timestamp in timeline:
        stamp = pd.Timestamp(timestamp)
        for symbol, series in closes.items():
            if stamp in series.index:
                last_prices[symbol] = Decimal(str(series.loc[stamp]))
        realized_pnl = sum(
            (
                trade.net_pnl
                for trade in result.trades
                if trade.exit_time and trade.exit_time <= timestamp
            ),
            Decimal("0"),
        )
        realized = result.initial_equity + realized_pnl
        unrealized = Decimal("0")
        gross = Decimal("0")
        open_count = 0
        for trade in result.trades:
            if trade.entry_time > timestamp or (trade.exit_time and trade.exit_time <= timestamp):
                continue
            mark = last_prices.get(trade.symbol)
            if mark is None:
                continue
            open_count += 1
            gross += abs(mark * trade.quantity)
            liquidation = mark * (Decimal("1") - slippage_bps / Decimal("10000"))
            estimated_commission = (
                (trade.entry_price + liquidation)
                * trade.quantity
                * commission_bps
                / Decimal("10000")
            )
            unrealized += (liquidation - trade.entry_price) * trade.quantity - estimated_commission
        mtm = realized + unrealized
        peak = max(peak, mtm)
        curve.append(
            DailyEquity(
                timestamp,
                float(realized),
                float(mtm),
                float(unrealized),
                float(mtm / peak - 1),
                float(gross),
                float(gross / mtm * 100) if mtm else 0.0,
                open_count,
            )
        )
    return curve


def accounting_report(
    result: ReplayResult,
    frames: dict[str, pd.DataFrame],
    dataset_start: datetime,
    dataset_end: datetime,
    eligible_start: datetime,
    commission_bps: Decimal,
    slippage_bps: Decimal,
) -> dict[str, object]:
    timeline = sorted(
        {
            stamp.to_pydatetime()
            for frame in frames.values()
            for stamp in pd.to_datetime(frame.timestamp, utc=True)
        }
    )
    curve = portfolio_equity_curve(result, frames, timeline, commission_bps, slippage_bps)
    realized_equity = float(result.final_equity)
    mtm_equity = curve[-1].mtm_equity if curve else realized_equity
    initial = float(result.initial_equity)
    realized_return = realized_equity / initial - 1
    mtm_return = mtm_equity / initial - 1
    first_trade = min((trade.entry_time for trade in result.trades), default=None)
    daily = daily_risk_metrics([point.mtm_equity for point in curve])
    invested = [point for point in curve if point.open_positions > 0]
    open_trades = [trade for trade in result.trades if trade.state == ExecutionState.OPEN]
    return {
        "realized_only": {
            "final_equity": realized_equity,
            "net_pnl": realized_equity - initial,
            "total_return": realized_return,
            "open_positions_excluded": len(open_trades),
        },
        "mark_to_market": {
            "final_equity": mtm_equity,
            "net_pnl": mtm_equity - initial,
            "unrealized_pnl": mtm_equity - realized_equity,
            "total_return": mtm_return,
            **daily,
        },
        "periods": {
            "dataset": {
                "start": dataset_start.isoformat(),
                "end": dataset_end.isoformat(),
                "years": _years(dataset_start, dataset_end),
                "cagr": _cagr(mtm_return, _years(dataset_start, dataset_end)),
            },
            "eligible": {
                "start": eligible_start.isoformat(),
                "end": dataset_end.isoformat(),
                "years": _years(eligible_start, dataset_end),
                "cagr": _cagr(mtm_return, _years(eligible_start, dataset_end)),
            },
            "first_trade": None
            if first_trade is None
            else {
                "start": first_trade.isoformat(),
                "end": dataset_end.isoformat(),
                "years": _years(first_trade, dataset_end),
                "cagr": _cagr(mtm_return, _years(first_trade, dataset_end)),
            },
            "reported_cagr_basis": "dataset",
        },
        "risk_methodology": {
            "return_frequency": "daily mark-to-market portfolio equity",
            "annualization_factor": 252,
            "sharpe_formula": "mean(daily_return)/sample_std(daily_return)*sqrt(252)",
            "sortino_formula": "mean(daily_return)/sqrt(mean(min(return,0)^2))*sqrt(252)",
            "risk_free_rate": 0,
        },
        "exposure": {
            "average_gross_exposure_percent": float(
                np.mean([point.gross_exposure_percent for point in curve])
            )
            if curve
            else 0.0,
            "peak_gross_exposure_percent": max(
                (point.gross_exposure_percent for point in curve), default=0.0
            ),
            "time_invested_percent": len(invested) / len(curve) * 100 if curve else 0.0,
            "average_open_positions": float(np.mean([point.open_positions for point in curve]))
            if curve
            else 0.0,
        },
        "open_positions": [
            {
                "symbol": trade.symbol,
                "entry_time": trade.entry_time.isoformat(),
                "entry_price": float(trade.entry_price),
                "quantity": float(trade.quantity),
            }
            for trade in open_trades
        ],
        "daily_equity_curve": [asdict(point) for point in curve],
    }

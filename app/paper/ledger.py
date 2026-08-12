from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import uuid4


@dataclass
class PaperTrade:
    trade_id: str
    symbol: str
    signal_time: datetime
    entry_time: datetime
    entry_price: Decimal
    position_size: Decimal
    stop_price: Decimal
    target_1: Decimal
    target_2: Decimal
    exit_time: datetime | None = None
    exit_price: Decimal | None = None
    exit_reason: str | None = None
    gross_return: Decimal = Decimal("0")
    fees: Decimal = Decimal("0")
    slippage: Decimal = Decimal("0")
    net_return: Decimal = Decimal("0")


class PaperLedger:
    def __init__(
        self, commission_bps: Decimal = Decimal("10"), slippage_bps: Decimal = Decimal("5")
    ) -> None:
        self.commission_bps, self.slippage_bps = commission_bps, slippage_bps
        self.trades: list[PaperTrade] = []

    def open(
        self,
        symbol: str,
        when: datetime,
        entry: Decimal,
        size: Decimal,
        stop: Decimal,
        target_1: Decimal,
        target_2: Decimal,
    ) -> PaperTrade:
        if not (size > 0 and stop < entry < target_1 < target_2):
            raise ValueError("invalid paper trade")
        adjusted = entry * (1 + self.slippage_bps / Decimal("10000"))
        trade = PaperTrade(
            str(uuid4()),
            symbol,
            when,
            when,
            adjusted,
            size,
            stop,
            target_1,
            target_2,
            slippage=(adjusted - entry) * size,
        )
        self.trades.append(trade)
        return trade

    def close(self, trade_id: str, when: datetime, price: Decimal, reason: str) -> PaperTrade:
        trade = next(t for t in self.trades if t.trade_id == trade_id)
        if trade.exit_time:
            raise ValueError("trade already closed")
        adjusted = price * (1 - self.slippage_bps / Decimal("10000"))
        trade.exit_time, trade.exit_price, trade.exit_reason = when, adjusted, reason
        trade.gross_return = (adjusted - trade.entry_price) * trade.position_size
        trade.fees = (
            (trade.entry_price + adjusted)
            * trade.position_size
            * self.commission_bps
            / Decimal("10000")
        )
        trade.slippage += (price - adjusted) * trade.position_size
        trade.net_return = trade.gross_return - trade.fees
        return trade

    def performance(self) -> dict[str, float | int]:
        closed = [t for t in self.trades if t.exit_time]
        wins = [t for t in closed if t.net_return > 0]
        return {
            "number_of_trades": len(closed),
            "win_rate": len(wins) / len(closed) if closed else 0,
            "net_pnl": float(sum((t.net_return for t in closed), Decimal("0"))),
        }

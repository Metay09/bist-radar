from collections.abc import Callable
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.database.base import PaperTradeRow, SessionLocal
from app.paper.ledger import PaperLedger, PaperTrade


class DuplicateOpenTradeError(ValueError):
    pass


class PaperTradePersistenceError(RuntimeError):
    pass


class PaperTradeRepository:
    def __init__(self, session_factory: Callable[[], Session] = SessionLocal) -> None:
        self.session_factory = session_factory

    @staticmethod
    def _domain(row: PaperTradeRow) -> PaperTrade:
        return PaperTrade(
            row.trade_id,
            row.symbol,
            row.signal_time,
            row.entry_time,
            row.entry_price,
            row.position_size,
            row.stop_price,
            row.target_1,
            row.target_2,
            row.exit_time,
            row.exit_price,
            row.exit_reason,
            row.gross_return,
            row.fees,
            row.slippage,
            row.net_return,
        )

    def list(self) -> list[PaperTrade]:
        with self.session_factory() as session:
            rows = session.scalars(select(PaperTradeRow).order_by(PaperTradeRow.entry_time)).all()
            return [self._domain(row) for row in rows]

    def open(
        self,
        ledger: PaperLedger,
        symbol: str,
        when: datetime,
        entry: Decimal,
        size: Decimal,
        stop: Decimal,
        target_1: Decimal,
        target_2: Decimal,
    ) -> PaperTrade:
        trade = ledger.create(symbol, when, entry, size, stop, target_1, target_2)
        row = PaperTradeRow(
            trade_id=trade.trade_id,
            symbol=trade.symbol,
            active_symbol=trade.symbol,
            signal_time=trade.signal_time,
            entry_time=trade.entry_time,
            entry_price=trade.entry_price,
            position_size=trade.position_size,
            stop_price=trade.stop_price,
            target_1=trade.target_1,
            target_2=trade.target_2,
            gross_return=trade.gross_return,
            fees=trade.fees,
            slippage=trade.slippage,
            net_return=trade.net_return,
        )
        try:
            with self.session_factory() as session:
                with session.begin():
                    session.add(row)
        except IntegrityError as exc:
            raise DuplicateOpenTradeError(f"open trade already exists for {symbol}") from exc
        except SQLAlchemyError as exc:
            raise PaperTradePersistenceError("paper trade transaction failed") from exc
        return trade

    def close(
        self, ledger: PaperLedger, trade_id: str, when: datetime, price: Decimal, reason: str
    ) -> PaperTrade:
        try:
            with self.session_factory() as session:
                with session.begin():
                    row = session.scalar(
                        select(PaperTradeRow)
                        .where(PaperTradeRow.trade_id == trade_id)
                        .with_for_update()
                    )
                    if row is None:
                        raise KeyError(trade_id)
                    trade = ledger.close_trade(self._domain(row), when, price, reason)
                    row.active_symbol = None
                    row.exit_time = trade.exit_time
                    row.exit_price = trade.exit_price
                    row.exit_reason = trade.exit_reason
                    row.gross_return = trade.gross_return
                    row.fees = trade.fees
                    row.slippage = trade.slippage
                    row.net_return = trade.net_return
            return trade
        except (KeyError, ValueError):
            raise
        except SQLAlchemyError as exc:
            raise PaperTradePersistenceError("paper trade transaction failed") from exc

    def performance(self) -> dict[str, float | int]:
        return PaperLedger.performance_for(self.list())

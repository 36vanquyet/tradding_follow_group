from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ExecutionLog, PnLRecord, TradeOrder, TradeSignal


class Repository:
    def __init__(self, db: Session):
        self.db = db

    def create_signal(self, **kwargs) -> TradeSignal:
        signal = TradeSignal(**kwargs)
        self.db.add(signal)
        self.db.commit()
        self.db.refresh(signal)
        return signal

    def update_signal(self, signal: TradeSignal, **kwargs) -> TradeSignal:
        for key, value in kwargs.items():
            setattr(signal, key, value)
        signal.updated_at = datetime.utcnow()
        self.db.add(signal)
        self.db.commit()
        self.db.refresh(signal)
        return signal

    def add_order(self, **kwargs) -> TradeOrder:
        order = TradeOrder(**kwargs)
        self.db.add(order)
        self.db.commit()
        self.db.refresh(order)
        return order

    def log(self, message: str, level: str = "INFO", signal_id: int | None = None, context_json: str = "") -> None:
        item = ExecutionLog(signal_id=signal_id, message=message, level=level, context_json=context_json)
        self.db.add(item)
        self.db.commit()

    def list_signals(self, limit: int = 50) -> list[TradeSignal]:
        stmt = select(TradeSignal).order_by(TradeSignal.created_at.desc()).limit(limit)
        return list(self.db.scalars(stmt))

    def list_orders(self, limit: int = 100) -> list[TradeOrder]:
        stmt = select(TradeOrder).order_by(TradeOrder.created_at.desc()).limit(limit)
        return list(self.db.scalars(stmt))

    def get_signal(self, signal_id: int) -> TradeSignal | None:
        return self.db.get(TradeSignal, signal_id)

    def find_signal_by_symbol(self, symbol: str) -> TradeSignal | None:
        stmt = (
            select(TradeSignal)
            .where(TradeSignal.symbol == symbol)
            .order_by(TradeSignal.created_at.desc())
            .limit(1)
        )
        return self.db.scalar(stmt)

    def upsert_pnl(self, signal_id: int | None, symbol: str, side: str, qty: float, closed_pnl: float, fees: float, opened_at, closed_at) -> None:
        existing = self.db.scalar(
            select(PnLRecord).where(
                PnLRecord.symbol == symbol,
                PnLRecord.closed_at == closed_at,
                PnLRecord.qty == qty,
            )
        )
        if existing:
            existing.closed_pnl = closed_pnl
            existing.fees = fees
            existing.synced_at = datetime.utcnow()
            self.db.add(existing)
        else:
            self.db.add(
                PnLRecord(
                    signal_id=signal_id,
                    symbol=symbol,
                    side=side,
                    qty=qty,
                    closed_pnl=closed_pnl,
                    fees=fees,
                    opened_at=opened_at,
                    closed_at=closed_at,
                )
            )
        self.db.commit()

    def summary(self) -> dict:
        signal_count = self.db.scalar(select(func.count()).select_from(TradeSignal)) or 0
        pnl_total = self.db.scalar(select(func.coalesce(func.sum(PnLRecord.closed_pnl), 0.0))) or 0.0
        wins = self.db.scalar(select(func.count()).select_from(PnLRecord).where(PnLRecord.closed_pnl > 0)) or 0
        losses = self.db.scalar(select(func.count()).select_from(PnLRecord).where(PnLRecord.closed_pnl <= 0)) or 0
        return {"signals": signal_count, "closed_pnl": pnl_total, "wins": wins, "losses": losses}

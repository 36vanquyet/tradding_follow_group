from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TradeSignal(Base):
    __tablename__ = "trade_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    source_chat_id: Mapped[str] = mapped_column(String(64), index=True)
    source_chat_name: Mapped[str] = mapped_column(String(255), default="")
    raw_message: Mapped[str] = mapped_column(Text)

    symbol: Mapped[str] = mapped_column(String(64), index=True)
    side: Mapped[str] = mapped_column(String(8))
    entry_price: Mapped[float] = mapped_column(Float)
    stop_loss: Mapped[float] = mapped_column(Float)
    tp1: Mapped[float] = mapped_column(Float)
    tp2: Mapped[float] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    margin_usdt: Mapped[float] = mapped_column(Float, default=0.0)
    leverage: Mapped[int] = mapped_column(Integer, default=1)
    stop_loss_pct: Mapped[float] = mapped_column(Float, default=0.0)
    estimated_sl_loss_pct: Mapped[float] = mapped_column(Float, default=0.0)

    parsed_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    ai_reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), index=True, default="RECEIVED")
    error_message: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    orders: Mapped[list["TradeOrder"]] = relationship(back_populates="signal", cascade="all, delete-orphan")
    logs: Mapped[list["ExecutionLog"]] = relationship(back_populates="signal", cascade="all, delete-orphan")
    pnl_records: Mapped[list["PnLRecord"]] = relationship(back_populates="signal", cascade="all, delete-orphan")


class TradeOrder(Base):
    __tablename__ = "trade_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("trade_signals.id"), index=True)
    bybit_order_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    role: Mapped[str] = mapped_column(String(16))
    side: Mapped[str] = mapped_column(String(8))
    order_type: Mapped[str] = mapped_column(String(16))
    qty: Mapped[float] = mapped_column(Float)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    reduce_only: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="CREATED")
    raw_response: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    signal: Mapped["TradeSignal"] = relationship(back_populates="orders")


class ExecutionLog(Base):
    __tablename__ = "execution_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("trade_signals.id"), nullable=True, index=True)
    level: Mapped[str] = mapped_column(String(16), default="INFO")
    message: Mapped[str] = mapped_column(Text)
    context_json: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    signal: Mapped[TradeSignal | None] = relationship(back_populates="logs")


class PnLRecord(Base):
    __tablename__ = "pnl_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("trade_signals.id"), nullable=True, index=True)
    symbol: Mapped[str] = mapped_column(String(64), index=True)
    side: Mapped[str] = mapped_column(String(8))
    qty: Mapped[float] = mapped_column(Float, default=0.0)
    closed_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    fees: Mapped[float] = mapped_column(Float, default=0.0)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    signal: Mapped[TradeSignal | None] = relationship(back_populates="pnl_records")

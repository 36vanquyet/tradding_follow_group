from dataclasses import dataclass


@dataclass
class ParsedSignal:
    symbol: str
    side: str
    entry_price: float
    stop_loss: float
    tp1: float
    tp2: float


@dataclass
class AIDecision:
    approve: bool
    confidence: float
    reason: str


@dataclass
class PositionPlan:
    margin_usdt: float
    leverage: int
    qty: float
    stop_loss_pct: float
    estimated_sl_loss_pct: float

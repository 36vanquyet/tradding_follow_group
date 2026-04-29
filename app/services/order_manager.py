from datetime import datetime

from sqlalchemy.orm import Session

from app.config import Settings
from app.services.ai_decision import AIDecisionEngine
from app.services.bybit_service import BybitService
from app.services.repository import Repository
from app.services.signal_parser import SignalParser
from app.services.telegram_notifier import TelegramNotifier


class OrderManager:
    def __init__(self, settings: Settings, notifier: TelegramNotifier):
        self.settings = settings
        self.parser = SignalParser()
        self.ai_engine = AIDecisionEngine(settings)
        self.bybit = BybitService(settings)
        self.notifier = notifier

    async def process_message(self, db: Session, source_chat_id: str, source_chat_name: str, raw_message: str) -> None:
        repo = Repository(db)

        close_symbol = self.parser.parse_close_instruction(raw_message, self.settings.default_quote_asset)
        if close_symbol:
            result = self.bybit.close_symbol_position(close_symbol)
            if result.get("closed"):
                repo.log(
                    "Received manual close instruction and closed open position.",
                    context_json=self.bybit.dump(result),
                )
                await self.notifier.send(
                    f"Event captured from Telegram\n"
                    f"Type: CLOSE\n"
                    f"Symbol: {close_symbol}\n"
                    f"Status: closed open position"
                )
            else:
                repo.log(
                    "Received manual close instruction but no open position existed.",
                    context_json=self.bybit.dump(result),
                )
                await self.notifier.send(
                    f"Event captured from Telegram\n"
                    f"Type: CLOSE\n"
                    f"Symbol: {close_symbol}\n"
                    f"Status: no open position"
                )
            return

        parsed = self.parser.parse(raw_message, self.settings.default_quote_asset)
        if not parsed:
            repo.log("Skip message because signal format could not be parsed.", context_json=raw_message)
            return

        signal = repo.create_signal(
            source_chat_id=source_chat_id,
            source_chat_name=source_chat_name,
            raw_message=raw_message,
            symbol=parsed.symbol,
            side=parsed.side,
            entry_price=parsed.entry_price,
            stop_loss=parsed.stop_loss,
            tp1=parsed.tp1,
            tp2=parsed.tp2,
            parsed_ok=True,
            status="PARSED",
        )
        repo.log("Received new signal.", signal_id=signal.id, context_json=raw_message)
        await self.notifier.send(
            f"Event captured from Telegram\n"
            f"Source: {source_chat_name}\n"
            f"Signal #{signal.id}\n"
            f"{parsed.symbol} {parsed.side}\n"
            f"Entry {parsed.entry_price} | SL {parsed.stop_loss}\n"
            f"TP1 {parsed.tp1} | TP2 {parsed.tp2}"
        )

        decision = self.ai_engine.evaluate(parsed)
        approved = decision.approve and decision.confidence >= self.settings.ai_min_confidence
        repo.update_signal(
            signal,
            ai_approved=approved,
            ai_confidence=decision.confidence,
            ai_reason=decision.reason,
            status="APPROVED" if approved else "REJECTED",
        )
        await self.notifier.send(
            f"Signal #{signal.id} {parsed.symbol} {parsed.side}\nAI approve={approved} confidence={decision.confidence:.2f}\n{decision.reason}"
        )
        if not approved or not self.settings.ai_auto_approve:
            return

        try:
            result = self.bybit.place_signal_orders(parsed)
            plan = result["plan"]

            repo.update_signal(
                signal,
                quantity=plan.qty,
                margin_usdt=plan.margin_usdt,
                leverage=plan.leverage,
                stop_loss_pct=plan.stop_loss_pct,
                estimated_sl_loss_pct=plan.estimated_sl_loss_pct,
                status="ORDER_SUBMITTED",
            )

            repo.add_order(
                signal_id=signal.id,
                bybit_order_id=result["entry"]["result"]["orderId"],
                role="ENTRY",
                side=parsed.side,
                order_type="LIMIT",
                qty=plan.qty,
                price=parsed.entry_price,
                reduce_only=False,
                status="SUBMITTED",
                raw_response=self.bybit.dump(result["entry"]),
            )
            repo.add_order(
                signal_id=signal.id,
                bybit_order_id=result["sl"]["result"]["orderId"],
                role="SL",
                side="SELL" if parsed.side == "BUY" else "BUY",
                order_type="STOP_MARKET",
                qty=plan.qty,
                price=parsed.stop_loss,
                reduce_only=True,
                status="SUBMITTED",
                raw_response=self.bybit.dump(result["sl"]),
            )
            repo.add_order(
                signal_id=signal.id,
                bybit_order_id=result["tp1"]["result"]["orderId"],
                role="TP1",
                side="SELL" if parsed.side == "BUY" else "BUY",
                order_type="LIMIT",
                qty=max(round(plan.qty * self.settings.tp1_ratio, 3), 0.001),
                price=parsed.tp1,
                reduce_only=True,
                status="SUBMITTED",
                raw_response=self.bybit.dump(result["tp1"]),
            )
            repo.add_order(
                signal_id=signal.id,
                bybit_order_id=result["tp2"]["result"]["orderId"],
                role="TP2",
                side="SELL" if parsed.side == "BUY" else "BUY",
                order_type="LIMIT",
                qty=max(round(plan.qty * self.settings.tp2_ratio, 3), 0.001),
                price=parsed.tp2,
                reduce_only=True,
                status="SUBMITTED",
                raw_response=self.bybit.dump(result["tp2"]),
            )
            repo.log("Submitted Bybit orders.", signal_id=signal.id, context_json=self.bybit.dump(result))
            await self.notifier.send(
                f"Submitted Bybit signal #{signal.id}\n"
                f"{parsed.symbol} {parsed.side}\n"
                f"Isolated {plan.leverage}x | Margin {plan.margin_usdt:.2f} USDT\n"
                f"Entry {parsed.entry_price} | SL {parsed.stop_loss}\n"
                f"TP1 {parsed.tp1} | TP2 {parsed.tp2}\n"
                f"Qty {plan.qty}\n"
                f"SL risk ~ {plan.estimated_sl_loss_pct * 100:.2f}% of margin"
            )
        except Exception as exc:
            repo.update_signal(signal, status="ERROR", error_message=str(exc))
            repo.log("Failed to place Bybit orders.", level="ERROR", signal_id=signal.id, context_json=str(exc))
            await self.notifier.send(f"Signal #{signal.id} failed on Bybit: {exc}")

    async def cancel_symbol(self, db: Session, symbol: str) -> str:
        repo = Repository(db)
        result = self.bybit.cancel_symbol_orders(symbol)
        signal = repo.find_signal_by_symbol(symbol)
        if signal:
            repo.update_signal(signal, status="CANCELLED")
            repo.log("Cancelled open orders for symbol.", signal_id=signal.id, context_json=self.bybit.dump(result))
        message = f"Sent cancel request for {symbol}"
        await self.notifier.send(message)
        return message

    def sync_closed_pnl(self, db: Session) -> dict[str, int]:
        repo = Repository(db)
        closed = self.bybit.get_closed_pnl()
        processed = 0
        matched = 0
        for item in closed:
            processed += 1
            symbol = item.get("symbol", "")
            signal = repo.find_signal_by_symbol(symbol) if symbol else None
            if signal:
                matched += 1
            repo.upsert_pnl(
                signal_id=signal.id if signal else None,
                symbol=symbol,
                side=item.get("side", ""),
                qty=float(item.get("closedSize", 0) or 0),
                closed_pnl=float(item.get("closedPnl", 0) or 0),
                fees=float(item.get("openFee", 0) or 0) + float(item.get("closeFee", 0) or 0),
                opened_at=self._timestamp(item.get("createdTime")),
                closed_at=self._timestamp(item.get("updatedTime")),
            )
            if signal and signal.status != "CLOSED":
                repo.update_signal(signal, status="CLOSED")
        return {"processed": processed, "matched": matched}

    @staticmethod
    def _timestamp(value):
        if not value:
            return None
        return datetime.utcfromtimestamp(int(value) / 1000)

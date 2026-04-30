import json
import math
import logging
from datetime import datetime, timezone
from dataclasses import replace
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP, ROUND_UP
from typing import Any

import pybit._helpers as pybit_helpers
import pybit._http_manager as pybit_http_manager
from pybit.unified_trading import HTTP

from app.config import Settings
from app.schemas import ParsedSignal, PositionPlan


class BybitService:
    def __init__(self, settings: Settings):
        self.settings = settings
        logging.getLogger("pybit").setLevel(logging.CRITICAL)
        logging.getLogger("pybit._http_manager").setLevel(logging.CRITICAL)
        self.session = HTTP(
            testnet=settings.bybit_testnet,
            api_key=settings.bybit_api_key,
            api_secret=settings.bybit_api_secret,
            recv_window=settings.bybit_recv_window_ms,
        )
        self._time_offset_ms = 0
        self._sync_time_offset()

    def build_position_plan(self, signal: ParsedSignal) -> PositionPlan:
        stop_loss_pct = self._stop_loss_pct(signal)
        if stop_loss_pct <= 0:
            raise ValueError("Stop loss is invalid for this entry/side.")

        raw_leverage = self.settings.target_sl_loss_pct / stop_loss_pct
        leverage = math.floor(raw_leverage)
        leverage = max(self.settings.min_leverage, min(self.settings.max_leverage, leverage))
        leverage = max(leverage, 1)

        qty = (self.settings.fixed_margin_usdt * leverage) / signal.entry_price
        qty = math.floor(qty * 1000) / 1000
        if qty <= 0:
            raise ValueError("Calculated quantity is invalid.")

        return PositionPlan(
            margin_usdt=self.settings.fixed_margin_usdt,
            leverage=leverage,
            qty=qty,
            stop_loss_pct=stop_loss_pct,
            estimated_sl_loss_pct=stop_loss_pct * leverage,
        )

    def place_signal_orders(self, signal: ParsedSignal) -> dict[str, Any]:
        instrument = self._get_instrument_info(signal.symbol)
        market_price = self._get_market_price(signal.symbol)
        entry_price = self._normalize_price(signal.entry_price, instrument, side=signal.side, purpose="entry")
        stop_loss = self._normalize_price(signal.stop_loss, instrument, side=signal.side, purpose="stop_loss")
        tp1 = self._normalize_price(signal.tp1, instrument, side=signal.side, purpose="tp1")
        tp2 = self._normalize_price(signal.tp2, instrument, side=signal.side, purpose="tp2")

        self._validate_signal_price_distance(signal.symbol, market_price, entry_price)
        self._validate_signal_price_distance(signal.symbol, market_price, stop_loss, kind="stop_loss")
        self._validate_signal_price_distance(signal.symbol, market_price, tp1, kind="tp1")
        self._validate_signal_price_distance(signal.symbol, market_price, tp2, kind="tp2")

        normalized_signal = replace(
            signal,
            entry_price=entry_price,
            stop_loss=stop_loss,
            tp1=tp1,
            tp2=tp2,
        )
        plan = self.build_position_plan(normalized_signal)
        side = signal.side.title()
        exit_side = "Sell" if side == "Buy" else "Buy"
        trigger_direction = 2 if side == "Buy" else 1

        self._set_isolated_mode(signal.symbol, plan.leverage)

        entry = self._private_call(
            "place_order",
            self.session.place_order,
            category=self.settings.bybit_category,
            symbol=signal.symbol,
            side=side,
            orderType="Limit",
            qty=str(plan.qty),
            price=self._format_price(entry_price, instrument),
            timeInForce="GTC",
        )

        sl = self._private_call(
            "place_order",
            self.session.place_order,
            category=self.settings.bybit_category,
            symbol=signal.symbol,
            side=exit_side,
            orderType="Market",
            qty=str(plan.qty),
            triggerPrice=self._format_price(stop_loss, instrument),
            triggerDirection=trigger_direction,
            reduceOnly=True,
            closeOnTrigger=True,
        )

        tp1_qty = max(round(plan.qty * self.settings.tp1_ratio, 3), 0.001)
        tp2_qty = max(round(plan.qty * self.settings.tp2_ratio, 3), 0.001)

        tp1 = self._private_call(
            "place_order",
            self.session.place_order,
            category=self.settings.bybit_category,
            symbol=signal.symbol,
            side=exit_side,
            orderType="Limit",
            qty=str(tp1_qty),
            price=self._format_price(tp1, instrument),
            timeInForce="GTC",
            reduceOnly=True,
        )
        tp2 = self._private_call(
            "place_order",
            self.session.place_order,
            category=self.settings.bybit_category,
            symbol=signal.symbol,
            side=exit_side,
            orderType="Limit",
            qty=str(tp2_qty),
            price=self._format_price(tp2, instrument),
            timeInForce="GTC",
            reduceOnly=True,
        )
        return {"plan": plan, "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2}

    def cancel_symbol_orders(self, symbol: str) -> dict[str, Any]:
        return self._private_call(
            "cancel_all_orders",
            self.session.cancel_all_orders,
            category=self.settings.bybit_category,
            symbol=symbol,
        )

    def cancel_all_orders(self) -> dict[str, Any]:
        try:
            return self._private_call(
                "cancel_all_orders",
                self.session.cancel_all_orders,
                category=self.settings.bybit_category,
            )
        except Exception:
            open_orders = self.get_open_orders()
            symbols = sorted({str(order.get("symbol", "")) for order in open_orders if order.get("symbol")})
            results: list[dict[str, Any]] = []
            for symbol in symbols:
                results.append(
                    self._private_call(
                        "cancel_all_orders",
                        self.session.cancel_all_orders,
                        category=self.settings.bybit_category,
                        symbol=symbol,
                    )
                )
            return {"result": results}

    def close_symbol_position(self, symbol: str) -> dict[str, Any]:
        position = self._get_open_position(symbol)
        if not position:
            return {"closed": False, "symbol": symbol, "reason": "no_open_position"}

        self.cancel_symbol_orders(symbol)

        side = str(position.get("side", "")).title()
        if side not in {"Buy", "Sell"}:
            raise ValueError(f"Unsupported position side for {symbol}: {side}")

        qty = float(position.get("size", 0) or 0)
        if qty <= 0:
            raise ValueError(f"No open quantity found for {symbol}.")

        close_side = "Sell" if side == "Buy" else "Buy"
        return self._private_call(
            "place_order",
            self.session.place_order,
            category=self.settings.bybit_category,
            symbol=symbol,
            side=close_side,
            orderType="Market",
            qty=str(qty),
            reduceOnly=True,
        )

    def close_all_positions(self) -> dict[str, Any]:
        self.cancel_all_orders()
        positions = self.get_positions()
        responses: list[dict[str, Any]] = []
        for position in positions:
            symbol = str(position.get("symbol", ""))
            size = float(position.get("size", 0) or 0)
            side = str(position.get("side", "")).title()
            if not symbol or size <= 0 or side not in {"Buy", "Sell"}:
                continue
            close_side = "Sell" if side == "Buy" else "Buy"
            response = self._private_call(
                "place_order",
                self.session.place_order,
                category=self.settings.bybit_category,
                symbol=symbol,
                side=close_side,
                orderType="Market",
                qty=str(size),
                reduceOnly=True,
                positionIdx=position.get("positionIdx", 0),
            )
            responses.append(response)
        return {"result": responses}

    def get_open_orders(self) -> list[dict[str, Any]]:
        response = self._private_call(
            "get_open_orders",
            self.session.get_open_orders,
            category=self.settings.bybit_category,
            settleCoin=self.settings.default_quote_asset,
        )
        return response.get("result", {}).get("list", [])

    def get_positions(self) -> list[dict[str, Any]]:
        response = self._private_call(
            "get_positions",
            self.session.get_positions,
            category=self.settings.bybit_category,
            settleCoin=self.settings.default_quote_asset,
        )
        return response.get("result", {}).get("list", [])

    def get_closed_pnl(self) -> list[dict[str, Any]]:
        response = self._private_call(
            "get_closed_pnl",
            self.session.get_closed_pnl,
            category=self.settings.bybit_category,
            limit=50,
        )
        return response.get("result", {}).get("list", [])

    def get_wallet_balance(self) -> dict[str, Any]:
        response = self._private_call(
            "get_wallet_balance",
            self.session.get_wallet_balance,
            accountType=self.settings.bybit_account_type,
        )
        return self._parse_wallet_balance(response)

    def _get_open_position(self, symbol: str) -> dict[str, Any] | None:
        positions = self.get_positions()
        for position in positions:
            if position.get("symbol") == symbol and float(position.get("size", 0) or 0) > 0:
                return position
        return None

    def _parse_wallet_balance(self, response: dict[str, Any]) -> dict[str, Any]:
        result = response.get("result", {})
        account_list = result.get("list", [])
        account = account_list[0] if account_list else {}
        coins = account.get("coin", []) if isinstance(account, dict) else []
        coin_map = {str(item.get("coin", "")).upper(): item for item in coins if item.get("coin")}
        target_coin = coin_map.get(self.settings.default_quote_asset.upper(), {})
        return {
            "account_type": self.settings.bybit_account_type,
            "total_equity": self._as_float(account.get("totalEquity")),
            "wallet_balance": self._as_float(account.get("walletBalance")),
            "available_balance": self._as_float(account.get("availableToWithdraw") or account.get("availableBalance")),
            "available_to_withdraw": self._as_float(account.get("availableToWithdraw")),
            "coin": self.settings.default_quote_asset.upper(),
            "coin_wallet_balance": self._as_float(target_coin.get("walletBalance")),
            "coin_equity": self._as_float(target_coin.get("equity")),
            "coin_available_to_withdraw": self._as_float(target_coin.get("availableToWithdraw")),
            "raw": response,
        }

    def _sync_time_offset(self) -> None:
        try:
            response = self.session.get_server_time()
            server_time_ms = int(response["result"]["timeNano"]) // 1_000_000 if "timeNano" in response.get("result", {}) else int(response["result"]["timeSecond"]) * 1000
            local_time_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            self._time_offset_ms = server_time_ms - local_time_ms - self.settings.bybit_timestamp_safety_ms
            self._patch_pybit_timestamp()
        except Exception:
            self._time_offset_ms = 0

    def _bump_timestamp_safety(self) -> None:
        current = self.settings.bybit_timestamp_safety_ms
        self.settings.bybit_timestamp_safety_ms = min(
            current + self.settings.bybit_timestamp_safety_step_ms,
            self.settings.bybit_timestamp_safety_max_ms,
        )

    def _patch_pybit_timestamp(self) -> None:
        offset = self._time_offset_ms

        def patched_timestamp() -> int:
            return int(datetime.now(timezone.utc).timestamp() * 1000) + offset

        pybit_helpers.generate_timestamp = patched_timestamp
        pybit_http_manager._helpers.generate_timestamp = patched_timestamp

    def _private_call(self, name: str, fn, *args, **kwargs):
        self._sync_time_offset()
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            if self._is_timestamp_error(exc):
                self._bump_timestamp_safety()
                self._sync_time_offset()
                return fn(*args, **kwargs)
            raise

    @staticmethod
    def _is_timestamp_error(exc: Exception) -> bool:
        text = str(exc)
        return "ErrCode: 10002" in text or "recv_window" in text or "timestamp" in text

    @staticmethod
    def _as_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _set_isolated_mode(self, symbol: str, leverage: int) -> None:
        try:
            self._private_call(
                "switch_margin_mode",
                self.session.switch_margin_mode,
                category=self.settings.bybit_category,
                symbol=symbol,
                tradeMode=1,
                buyLeverage=str(leverage),
                sellLeverage=str(leverage),
            )
        except Exception:
            pass

        self._private_call(
            "set_leverage",
            self.session.set_leverage,
            category=self.settings.bybit_category,
            symbol=symbol,
            buyLeverage=str(leverage),
            sellLeverage=str(leverage),
        )

    def _get_market_price(self, symbol: str) -> float:
        response = self._private_call(
            "get_tickers",
            self.session.get_tickers,
            category=self.settings.bybit_category,
            symbol=symbol,
        )
        items = response.get("result", {}).get("list", [])
        if not items:
            raise ValueError(f"Unable to fetch market price for {symbol}.")
        item = items[0]
        for key in ("markPrice", "lastPrice", "indexPrice"):
            value = item.get(key)
            if value not in (None, ""):
                return float(value)
        raise ValueError(f"Unable to determine market price for {symbol}.")

    def _get_instrument_info(self, symbol: str) -> dict[str, Any]:
        response = self._private_call(
            "get_instruments_info",
            self.session.get_instruments_info,
            category=self.settings.bybit_category,
            symbol=symbol,
        )
        items = response.get("result", {}).get("list", [])
        if not items:
            raise ValueError(f"Unable to fetch instrument info for {symbol}.")
        item = items[0]
        price_filter = item.get("priceFilter", {}) if isinstance(item, dict) else {}
        lot_size = item.get("lotSizeFilter", {}) if isinstance(item, dict) else {}
        return {
            "tick_size": self._as_float(price_filter.get("tickSize")),
            "min_price": self._as_float(price_filter.get("minPrice")),
            "max_price": self._as_float(price_filter.get("maxPrice")),
            "qty_step": self._as_float(lot_size.get("qtyStep")),
            "min_qty": self._as_float(lot_size.get("minOrderQty")),
            "max_qty": self._as_float(lot_size.get("maxOrderQty")),
        }

    def _normalize_price(self, price: float, instrument: dict[str, Any], *, side: str, purpose: str) -> float:
        value = self._as_float(price)
        tick_size = self._as_float(instrument.get("tick_size")) or 0.0
        if value <= 0:
            raise ValueError(f"{purpose} price is invalid.")
        if tick_size > 0:
            decimals = max(0, self._tick_decimals(tick_size))
            if side == "BUY" and purpose == "entry":
                value = math.floor(value / tick_size) * tick_size
            elif side == "SELL" and purpose == "entry":
                value = math.ceil(value / tick_size) * tick_size
            else:
                value = round(value / tick_size) * tick_size
            value = round(value, decimals)
        min_price = self._as_float(instrument.get("min_price"))
        max_price = self._as_float(instrument.get("max_price"))
        if min_price and value < min_price:
            raise ValueError(f"{purpose} price {value} is below Bybit minimum {min_price}.")
        if max_price and value > max_price:
            raise ValueError(f"{purpose} price {value} is above Bybit maximum {max_price}.")
        return value

    def _validate_signal_price_distance(self, symbol: str, market_price: float, price: float, *, kind: str = "entry") -> None:
        if market_price <= 0 or price <= 0:
            return
        deviation = abs(price - market_price) / market_price
        if deviation > self.settings.max_signal_price_deviation_pct:
            raise ValueError(
                f"{kind} price {price} for {symbol} deviates too far from market price {market_price:.6f} "
                f"(>{self.settings.max_signal_price_deviation_pct * 100:.0f}%)."
            )

    @staticmethod
    def _tick_decimals(tick_size: float) -> int:
        text = f"{tick_size:.20f}".rstrip("0")
        if "." not in text:
            return 0
        return len(text.split(".", 1)[1])

    @staticmethod
    def _format_price(price: float, instrument: dict[str, Any]) -> str:
        tick_size = BybitService._as_float(instrument.get("tick_size"))
        if tick_size > 0:
            decimals = max(0, BybitService._tick_decimals(tick_size))
            quant = Decimal(str(tick_size))
            rounded = (Decimal(str(price)) / quant).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * quant
            return format(rounded.quantize(Decimal(10) ** -decimals), "f")
        return str(price)

    @staticmethod
    def _stop_loss_pct(signal: ParsedSignal) -> float:
        if signal.entry_price <= 0:
            return 0.0
        if signal.side == "BUY":
            return (signal.entry_price - signal.stop_loss) / signal.entry_price
        return (signal.stop_loss - signal.entry_price) / signal.entry_price

    @staticmethod
    def dump(response: Any) -> str:
        return json.dumps(response, ensure_ascii=False, default=str)

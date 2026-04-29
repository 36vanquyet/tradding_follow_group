from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Any

from openai import APIConnectionError, APIError, AuthenticationError, BadRequestError, RateLimitError

from app.config import Settings
from app.schemas import NormalizedTelegramMessage
from app.services.llm_client import build_llm_client
from app.services.signal_parser import SignalParser


class MessageNormalizer:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client, self.provider_name = build_llm_client(settings)
        self.provider_disabled = False
        self.fallback_parser = SignalParser()

    def normalize(self, raw_message: str, default_quote_asset: str) -> NormalizedTelegramMessage:
        if self.client and not self.provider_disabled:
            try:
                parsed = self._normalize_with_openai(raw_message, default_quote_asset)
                if parsed and parsed.kind in {"SIGNAL", "CLOSE"}:
                    return parsed
            except (RateLimitError, AuthenticationError, BadRequestError, APIConnectionError, APIError, json.JSONDecodeError):
                self.provider_disabled = True
        return self._normalize_with_regex(raw_message, default_quote_asset)

    def _normalize_with_openai(self, raw_message: str, default_quote_asset: str) -> NormalizedTelegramMessage | None:
        prompt = {
            "task": "Convert a Telegram trading message into strict JSON for automated execution.",
            "rules": [
                "Return JSON only.",
                "Do not invent values that are not in the message.",
                "If the message is a close/exit instruction, set kind to CLOSE and only include the symbol if present.",
                "If the message is not actionable, set kind to UNKNOWN.",
                "Normalize all numbers as JSON numbers.",
                "Symbol should be the base asset only when the quote asset is obvious, otherwise use the exact symbol from the message.",
                "Ignore emojis and decorative characters.",
                "Handle Vietnamese and English variants, including Xu huong tang/giam, Vung tham chieu, Nguong rui ro, Khang cu, Ho tro.",
            ],
            "desired_output": {
                "kind": "SIGNAL|CLOSE|UNKNOWN",
                "symbol": "LINK",
                "side": "BUY|SELL|",
                "entry_price": 0.0,
                "stop_loss": 0.0,
                "tp1": 0.0,
                "tp2": 0.0,
                "confidence": 0.0,
                "reason": "short reason",
            },
            "default_quote_asset": default_quote_asset,
            "message": raw_message,
        }
        response = self.client.responses.create(
            model=self.settings.groq_model if self.provider_name == "groq" else self.settings.openai_model,
            instructions=(
                "You extract Telegram trade signals into strict JSON. "
                "If the message is not a trade signal or close instruction, return kind UNKNOWN. "
                "Never add markdown fences or commentary."
            ),
            input=json.dumps(prompt, ensure_ascii=False),
            max_output_tokens=400,
            temperature=0,
        )
        payload = self._extract_json(response.output_text)
        return self._coerce_payload(payload, parser_source=self.provider_name, default_quote_asset=default_quote_asset)

    def _normalize_with_regex(self, raw_message: str, default_quote_asset: str) -> NormalizedTelegramMessage:
        close_symbol = self.fallback_parser.parse_close_instruction(raw_message, default_quote_asset)
        if close_symbol:
            data = NormalizedTelegramMessage(
                kind="CLOSE",
                status="PARSED",
                parser_source="regex",
                confidence=0.72,
                reason="Matched close instruction fallback parser.",
                symbol=close_symbol,
                normalized_json="",
            )
            data.normalized_json = json.dumps(asdict(data), ensure_ascii=False)
            return data

        parsed = self.fallback_parser.parse(raw_message, default_quote_asset)
        if parsed:
            data = NormalizedTelegramMessage(
                kind="SIGNAL",
                status="PARSED",
                parser_source="regex",
                confidence=0.68,
                reason="Matched signal format fallback parser.",
                symbol=parsed.symbol,
                side=parsed.side,
                entry_price=parsed.entry_price,
                stop_loss=parsed.stop_loss,
                tp1=parsed.tp1,
                tp2=parsed.tp2,
                normalized_json="",
            )
            data.normalized_json = json.dumps(asdict(data), ensure_ascii=False)
            return data

        data = NormalizedTelegramMessage(
            kind="UNKNOWN",
            status="SKIPPED",
            parser_source="regex",
            confidence=0.0,
            reason="Signal format could not be parsed.",
            normalized_json="",
        )
        data.normalized_json = json.dumps(asdict(data), ensure_ascii=False)
        return data

    def _coerce_payload(self, payload: Any, *, parser_source: str, default_quote_asset: str) -> NormalizedTelegramMessage | None:
        if not isinstance(payload, dict):
            return None

        kind = str(payload.get("kind", "UNKNOWN")).upper()
        symbol = self._normalize_symbol(str(payload.get("symbol", "")), default_quote_asset)
        side = self._normalize_side(payload.get("side"))
        entry_price = self._to_float(payload.get("entry_price"))
        stop_loss = self._to_float(payload.get("stop_loss"))
        tp1 = self._to_float(payload.get("tp1"))
        tp2 = self._to_float(payload.get("tp2"))
        confidence = self._clamp_confidence(payload.get("confidence"))
        reason = str(payload.get("reason", "")).strip()

        if kind == "SIGNAL" and not (symbol and side and entry_price and stop_loss and tp1 and tp2):
            return None
        if kind == "CLOSE" and not symbol:
            return None

        data = NormalizedTelegramMessage(
            kind=kind if kind in {"SIGNAL", "CLOSE", "UNKNOWN"} else "UNKNOWN",
            status="PARSED" if kind in {"SIGNAL", "CLOSE"} else "SKIPPED",
            parser_source=parser_source,
            confidence=confidence,
            reason=reason or (f"Parsed by {parser_source}." if kind in {"SIGNAL", "CLOSE"} else "Not actionable."),
            symbol=symbol,
            side=side,
            entry_price=entry_price or 0.0,
            stop_loss=stop_loss or 0.0,
            tp1=tp1 or 0.0,
            tp2=tp2 or 0.0,
            normalized_json="",
        )
        data.normalized_json = json.dumps(asdict(data), ensure_ascii=False)
        return data

    def _extract_json(self, text: str) -> Any:
        stripped = text.strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", stripped, re.DOTALL | re.IGNORECASE)
        if fenced:
            return json.loads(fenced.group(1))
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            return json.loads(stripped[start : end + 1])
        return json.loads(stripped)

    @staticmethod
    def _normalize_symbol(symbol: str, default_quote_asset: str) -> str:
        symbol = symbol.strip().upper().lstrip("#")
        if not symbol:
            return ""
        if symbol.endswith(default_quote_asset):
            return symbol
        if symbol.isalpha() and len(symbol) <= 20:
            return f"{symbol}{default_quote_asset}"
        return symbol

    @staticmethod
    def _normalize_side(value: Any) -> str:
        side = str(value or "").upper()
        if side in {"BUY", "LONG"}:
            return "BUY"
        if side in {"SELL", "SHORT"}:
            return "SELL"
        return ""

    @staticmethod
    def _to_float(value: Any) -> float:
        try:
            if value in (None, "", False):
                return 0.0
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _clamp_confidence(value: Any) -> float:
        confidence = MessageNormalizer._to_float(value)
        if confidence < 0:
            return 0.0
        if confidence > 1:
            return 1.0
        return confidence

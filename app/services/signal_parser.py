import re
import unicodedata
from typing import Optional

from app.schemas import ParsedSignal


class SignalParser:
    _pair_patterns = [
        re.compile(r"PAIR:\s*#?([A-Z0-9]+)", re.IGNORECASE),
        re.compile(r"COIN:\s*#?([A-Z0-9]+)", re.IGNORECASE),
        re.compile(r"#([A-Z0-9]{2,20})", re.IGNORECASE),
    ]
    _type_pattern = re.compile(r"TYPE:\s*(BUY|SELL|LONG|SHORT)", re.IGNORECASE)
    _trend_buy_patterns = [
        re.compile(r"XU HUONG\s*TANG", re.IGNORECASE),
        re.compile(r"XU HUONG\s*LONG", re.IGNORECASE),
        re.compile(r"BULLISH", re.IGNORECASE),
        re.compile(r"UPTREND", re.IGNORECASE),
    ]
    _trend_sell_patterns = [
        re.compile(r"XU HUONG\s*GIAM", re.IGNORECASE),
        re.compile(r"XU HUONG\s*SHORT", re.IGNORECASE),
        re.compile(r"BEARISH", re.IGNORECASE),
        re.compile(r"DOWNTREND", re.IGNORECASE),
    ]
    _entry_patterns = [
        re.compile(r"ENTRY:\s*([0-9]*\.?[0-9]+)", re.IGNORECASE),
        re.compile(r"VUNG THAM CHIEU:\s*([0-9]*\.?[0-9]+)", re.IGNORECASE),
    ]
    _sl_patterns = [
        re.compile(r"SL:\s*([0-9]*\.?[0-9]+)", re.IGNORECASE),
        re.compile(r"NGUONG RUI RO:\s*([0-9]*\.?[0-9]+)", re.IGNORECASE),
    ]
    _tp1_patterns = [
        re.compile(r"TP1:\s*([0-9]*\.?[0-9]+)", re.IGNORECASE),
        re.compile(r"HO TRO 1:\s*([0-9]*\.?[0-9]+)", re.IGNORECASE),
    ]
    _tp2_patterns = [
        re.compile(r"TP2:\s*([0-9]*\.?[0-9]+)", re.IGNORECASE),
        re.compile(r"HO TRO 2:\s*([0-9]*\.?[0-9]+)", re.IGNORECASE),
    ]
    _close_instruction_patterns = [
        # Close / exit instructions with common Vietnamese synonyms.
        # Keep the symbol requirement explicit to avoid false positives.
        re.compile(
            r"\b(?:DONG|CHOT|CAT|THOAT)\s+(?:SOM\s+)?(?:LENH\s+|VI THE\s+|POSITION\s+|GIAO DICH\s+)?#?([A-Z0-9]{2,20})\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:DONG|CHOT|CAT|THOAT)\s+#?([A-Z0-9]{2,20})\b",
            re.IGNORECASE,
        ),
        re.compile(r"\bCLOSE\s+#?([A-Z0-9]{2,20})\b", re.IGNORECASE),
        re.compile(r"\bEXIT\s+#?([A-Z0-9]{2,20})\b", re.IGNORECASE),
    ]

    def parse(self, raw_message: str, default_quote_asset: str) -> Optional[ParsedSignal]:
        normalized = self._normalize(raw_message)

        symbol = self._match_first(self._pair_patterns, normalized)
        type_text = self._match_single(self._type_pattern, normalized)
        if not type_text:
            if self._matches_any(self._trend_buy_patterns, normalized):
                type_text = "BUY"
            elif self._matches_any(self._trend_sell_patterns, normalized):
                type_text = "SELL"

        entry = self._match_first(self._entry_patterns, normalized)
        stop_loss = self._match_first(self._sl_patterns, normalized)
        tp1 = self._match_first(self._tp1_patterns, normalized)
        tp2 = self._match_first(self._tp2_patterns, normalized)

        if not all([symbol, type_text, entry, stop_loss, tp1, tp2]):
            return None

        side = type_text.upper()
        side = "BUY" if side in {"BUY", "LONG"} else "SELL"
        if not symbol.endswith(default_quote_asset):
            symbol = f"{symbol}{default_quote_asset}"

        return ParsedSignal(
            symbol=symbol,
            side=side,
            entry_price=float(entry),
            stop_loss=float(stop_loss),
            tp1=float(tp1),
            tp2=float(tp2),
        )

    def parse_close_instruction(self, raw_message: str, default_quote_asset: str) -> Optional[str]:
        normalized = self._normalize(raw_message)
        symbol = self._match_first(self._close_instruction_patterns, normalized)
        if not symbol:
            return None
        symbol = symbol.upper()
        if not symbol.endswith(default_quote_asset):
            symbol = f"{symbol}{default_quote_asset}"
        return symbol

    def _normalize(self, raw_message: str) -> str:
        text = raw_message.replace("Đ", "D").replace("đ", "d")
        text = unicodedata.normalize("NFKD", text)
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = text.encode("ascii", "ignore").decode("ascii")
        text = text.upper()
        for old in ["🔸", "❌", "✅", "⚠", "📉", "📈", "—", "-", "/"]:
            text = text.replace(old, " ")
        return text

    def _match_first(self, patterns, text: str) -> Optional[str]:
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                return match.group(1)
        return None

    def _match_single(self, pattern, text: str) -> Optional[str]:
        match = pattern.search(text)
        if match:
            return match.group(1)
        return None

    def _matches_any(self, patterns, text: str) -> bool:
        return any(pattern.search(text) for pattern in patterns)

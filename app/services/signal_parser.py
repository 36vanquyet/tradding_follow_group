import re
import unicodedata
from typing import Optional

from app.schemas import ParsedSignal


class SignalParser:
    _number_pattern = r"([0-9][0-9,]*(?:\.[0-9]+)?)"
    _pair_patterns = [
        re.compile(r"PAIR:\s*#?([A-Z0-9]+)", re.IGNORECASE),
        re.compile(r"COIN:\s*#?([A-Z0-9]+)", re.IGNORECASE),
        re.compile(r"#([A-Z0-9]{2,20})", re.IGNORECASE),
    ]
    _type_pattern = re.compile(r"TYPE:\s*(BUY|SELL|LONG|SHORT)", re.IGNORECASE)
    _entry_labels = [
        "ENTRY",
        "VUNG THAM CHIEU",
        "VUNG VAO LENH",
        "GIA VAO LENH",
    ]
    _sl_labels = [
        "SL",
        "STOP LOSS",
        "NGUONG RUI RO",
        "DIEM CAT LO",
    ]
    _buy_tp1_labels = [
        "TP1",
        "TAKE PROFIT 1",
        "KHANG CU 1",
        "MUC TIEU 1",
        "TARGET 1",
        "HO TRO 1",
    ]
    _buy_tp2_labels = [
        "TP2",
        "TAKE PROFIT 2",
        "KHANG CU 2",
        "MUC TIEU 2",
        "TARGET 2",
        "HO TRO 2",
    ]
    _sell_tp1_labels = [
        "TP1",
        "TAKE PROFIT 1",
        "HO TRO 1",
        "MUC TIEU 1",
        "TARGET 1",
        "KHANG CU 1",
    ]
    _sell_tp2_labels = [
        "TP2",
        "TAKE PROFIT 2",
        "HO TRO 2",
        "MUC TIEU 2",
        "TARGET 2",
        "KHANG CU 2",
    ]
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

        side = self._canonical_side(type_text)
        entry = self._match_labeled_number(normalized, self._entry_labels)
        stop_loss = self._match_labeled_number(normalized, self._sl_labels)
        if side == "SELL":
            tp1 = self._match_labeled_number(normalized, self._sell_tp1_labels)
            tp2 = self._match_labeled_number(normalized, self._sell_tp2_labels)
        else:
            tp1 = self._match_labeled_number(normalized, self._buy_tp1_labels)
            tp2 = self._match_labeled_number(normalized, self._buy_tp2_labels)

        if not all([symbol, type_text, entry, stop_loss, tp1, tp2]):
            return None

        side = self._canonical_side(type_text)
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

    def _match_labeled_number(self, text: str, labels: list[str]) -> Optional[str]:
        for label in labels:
            pattern = re.compile(rf"\b{re.escape(label)}\s*:\s*{self._number_pattern}\b", re.IGNORECASE)
            match = pattern.search(text)
            if match:
                return self._normalize_number(match.group(1))
        return None

    def _matches_any(self, patterns, text: str) -> bool:
        return any(pattern.search(text) for pattern in patterns)

    @staticmethod
    def _canonical_side(type_text: Optional[str]) -> str:
        side = (type_text or "").upper()
        return "BUY" if side in {"BUY", "LONG"} else "SELL"

    @staticmethod
    def _normalize_number(value: str) -> str:
        return value.replace(",", "")

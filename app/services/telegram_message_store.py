from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class TelegramMessageStore:
    def __init__(self, path: str, max_items: int = 500):
        self.path = Path(path)
        self.max_items = max_items
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write_state({"messages": []})

    def record_received(
        self,
        *,
        chat_id: str,
        chat_name: str,
        telegram_message_id: int | None,
        raw_message: str,
    ) -> str:
        record_id = str(uuid.uuid4())
        now = self._now()
        record = {
            "id": record_id,
            "chat_id": chat_id,
            "chat_name": chat_name,
            "telegram_message_id": telegram_message_id,
            "raw_message": raw_message,
            "kind": "UNKNOWN",
            "status": "RECEIVED",
            "parser_source": "",
            "confidence": 0.0,
            "reason": "",
            "signal_id": None,
            "symbol": "",
            "side": "",
            "entry_price": 0.0,
            "stop_loss": 0.0,
            "tp1": 0.0,
            "tp2": 0.0,
            "normalized_json": "",
            "error_message": "",
            "created_at": now,
            "updated_at": now,
        }
        with self._lock:
            state = self._read_state()
            state["messages"].append(record)
            state["messages"] = self._trim(state["messages"])
            self._write_state(state)
        return record_id

    def mark_parsed(
        self,
        record_id: str,
        *,
        kind: str,
        parser_source: str,
        confidence: float,
        reason: str,
        signal_id: int | None = None,
        symbol: str = "",
        side: str = "",
        entry_price: float = 0.0,
        stop_loss: float = 0.0,
        tp1: float = 0.0,
        tp2: float = 0.0,
        normalized_json: str = "",
    ) -> bool:
        return self._update_record(
            record_id,
            lambda item: item.update(
                {
                    "kind": kind,
                    "status": "PARSED",
                    "parser_source": parser_source,
                    "confidence": confidence,
                    "reason": reason,
                    "signal_id": signal_id,
                    "symbol": symbol,
                    "side": side,
                    "entry_price": entry_price,
                    "stop_loss": stop_loss,
                    "tp1": tp1,
                    "tp2": tp2,
                    "normalized_json": normalized_json,
                    "error_message": "",
                }
            ),
        )

    def mark_skipped(self, record_id: str, *, reason: str, parser_source: str = "regex", normalized_json: str = "") -> bool:
        return self._update_record(
            record_id,
            lambda item: item.update(
                {
                    "kind": "UNKNOWN",
                    "status": "SKIPPED",
                    "parser_source": parser_source,
                    "confidence": 0.0,
                    "reason": reason,
                    "normalized_json": normalized_json,
                    "error_message": reason,
                }
            ),
        )

    def mark_error(self, record_id: str, *, error_message: str, parser_source: str = "", normalized_json: str = "") -> bool:
        return self._update_record(
            record_id,
            lambda item: item.update(
                {
                    "status": "ERROR",
                    "parser_source": parser_source,
                    "normalized_json": normalized_json,
                    "error_message": error_message,
                }
            ),
        )

    def list_messages(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            state = self._read_state()
            messages = list(reversed(state["messages"]))
            return messages[:limit]

    def summary(self) -> dict[str, int]:
        counts = {
            "total": 0,
            "received": 0,
            "parsed": 0,
            "skipped": 0,
            "error": 0,
        }
        with self._lock:
            state = self._read_state()
            counts["total"] = len(state["messages"])
            for item in state["messages"]:
                status = str(item.get("status", "")).lower()
                if status in counts:
                    counts[status] += 1
        return counts

    def _update_record(self, record_id: str, mutator) -> bool:
        with self._lock:
            state = self._read_state()
            for item in state["messages"]:
                if item.get("id") == record_id:
                    mutator(item)
                    item["updated_at"] = self._now()
                    self._write_state(state)
                    return True
        return False

    def _read_state(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"messages": []}
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except json.JSONDecodeError:
            corrupt_path = self.path.with_name(f"{self.path.stem}.corrupt-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{self.path.suffix}")
            self.path.replace(corrupt_path)
            return {"messages": []}
        if not isinstance(data, dict):
            return {"messages": []}
        messages = data.get("messages", [])
        if not isinstance(messages, list):
            messages = []
        data["messages"] = messages
        return data

    def _write_state(self, state: dict[str, Any]) -> None:
        payload = json.dumps(state, ensure_ascii=False, indent=2)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            handle.write(payload)
        temp_path.replace(self.path)

    def _trim(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self.max_items <= 0:
            return messages
        if len(messages) <= self.max_items:
            return messages
        return messages[-self.max_items :]

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

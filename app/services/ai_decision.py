import json

from openai import OpenAI

from app.config import Settings
from app.schemas import AIDecision, ParsedSignal


class AIDecisionEngine:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None

    def evaluate(self, signal: ParsedSignal) -> AIDecision:
        rr = self._risk_reward(signal)
        if rr <= 0.8:
            return AIDecision(False, 0.15, f"Risk/reward quá thấp ({rr:.2f}).")

        if not self.client:
            return AIDecision(True, min(0.7, max(0.56, rr / 3)), "Không có OpenAI API key, dùng luật fallback.")

        prompt = {
            "task": "Evaluate whether this futures trading signal should be auto-executed.",
            "rules": [
                "Reject if stop loss is on the wrong side of entry.",
                "Reject if both TP levels are inconsistent with the side.",
                "Prefer signals with reasonable reward/risk.",
                "Return concise JSON only.",
            ],
            "signal": {
                "symbol": signal.symbol,
                "side": signal.side,
                "entry_price": signal.entry_price,
                "stop_loss": signal.stop_loss,
                "tp1": signal.tp1,
                "tp2": signal.tp2,
                "risk_reward_tp2": rr,
            },
            "output_schema": {"approve": True, "confidence": 0.0, "reason": "short reason"},
        }
        response = self.client.responses.create(
            model=self.settings.openai_model,
            input=[
                {
                    "role": "system",
                    "content": "You are a strict futures signal risk filter. Output only valid JSON.",
                },
                {"role": "user", "content": json.dumps(prompt)},
            ],
        )
        raw = response.output_text.strip()
        data = json.loads(raw)
        return AIDecision(
            approve=bool(data["approve"]),
            confidence=float(data["confidence"]),
            reason=str(data["reason"]),
        )

    def _risk_reward(self, signal: ParsedSignal) -> float:
        if signal.side == "BUY":
            risk = signal.entry_price - signal.stop_loss
            reward = signal.tp2 - signal.entry_price
        else:
            risk = signal.stop_loss - signal.entry_price
            reward = signal.entry_price - signal.tp2
        if risk <= 0:
            return 0.0
        return reward / risk

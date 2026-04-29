import json

from openai import APIConnectionError, APIError, AuthenticationError, BadRequestError, RateLimitError

from app.config import Settings
from app.schemas import AIDecision, ParsedSignal
from app.services.llm_client import build_llm_client


class AIDecisionEngine:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client, self.provider_name = build_llm_client(settings)
        self.provider_disabled = False

    def evaluate(self, signal: ParsedSignal) -> AIDecision:
        rr = self._risk_reward(signal)
        if rr <= 0.8:
            return AIDecision(False, 0.15, f"Risk/reward quá thấp ({rr:.2f}).")

        if not self.client or self.provider_disabled:
            return self._fallback_decision(rr, "No LLM key or LLM disabled.")

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

        try:
            response = self.client.responses.create(
                model=self.settings.groq_model if self.provider_name == "groq" else self.settings.openai_model,
                instructions="You are a strict futures signal risk filter. Output only valid JSON.",
                input=json.dumps(prompt),
                max_output_tokens=200,
                temperature=0,
            )
            raw = response.output_text.strip()
            data = json.loads(raw)
            return AIDecision(
                approve=bool(data["approve"]),
                confidence=float(data["confidence"]),
                reason=str(data["reason"]),
            )
        except (RateLimitError, AuthenticationError, BadRequestError, APIConnectionError, APIError, json.JSONDecodeError) as exc:
            self.provider_disabled = True
            return self._fallback_decision(rr, f"LLM unavailable, using fallback. {exc}")

    def _fallback_decision(self, rr: float, reason: str) -> AIDecision:
        return AIDecision(True, min(0.7, max(0.56, rr / 3)), reason)

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

from __future__ import annotations

from openai import OpenAI

from app.config import Settings


def build_llm_client(settings: Settings):
    if settings.llm_provider.lower() == "groq" and settings.groq_api_key:
        return OpenAI(api_key=settings.groq_api_key, base_url=settings.groq_base_url), "groq"
    if settings.openai_api_key:
        return OpenAI(api_key=settings.openai_api_key), "openai"
    return None, "none"

"""Adapters for external text-generation providers."""

from app.infrastructure.llm.gemini import GeminiTextGenerationClient
from app.infrastructure.llm.openai import OpenAITextGenerationClient

__all__ = ["GeminiTextGenerationClient", "OpenAITextGenerationClient"]

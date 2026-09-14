"""Google Gemini adapter for the shared text-generation contract."""

from __future__ import annotations

import asyncio
from typing import Any, cast

from google import genai
from google.genai import types

from app.contracts.messages.llm import TextGenerationRequest, TextGenerationResponse
from app.contracts.ports.llm import ITextGenerationClient, TextGenerationError


class GeminiTextGenerationClient(ITextGenerationClient):
    """Generate plain or JSON-schema-constrained text with Gemini."""

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        timeout_seconds: float = 60.0,
    ) -> None:
        """Create a Gemini client that owns its SDK connection."""
        if not api_key.strip():
            raise ValueError("Gemini API key must not be empty.")
        if not model.strip():
            raise ValueError("Gemini model must not be empty.")
        if timeout_seconds <= 0:
            raise ValueError("Gemini timeout must be greater than zero.")
        self._client = genai.Client(api_key=api_key)
        self._model = model.strip()
        self._timeout_seconds = timeout_seconds

    async def generate(self, request: TextGenerationRequest) -> TextGenerationResponse:
        """Call Gemini asynchronously and return its generated text."""
        if request.output_schema is None:
            config = types.GenerateContentConfig(
                system_instruction=request.system_instruction,
                max_output_tokens=request.max_output_tokens,
            )
        else:
            config = types.GenerateContentConfig(
                system_instruction=request.system_instruction,
                max_output_tokens=request.max_output_tokens,
                response_mime_type="application/json",
                response_schema=cast(Any, request.output_schema),
            )

        try:
            async with asyncio.timeout(self._timeout_seconds):
                response = await self._client.aio.models.generate_content(
                    model=self._model,
                    contents=request.input_text,
                    config=config,
                )
            output_text = response.text
            if output_text is None or not output_text.strip():
                raise TextGenerationError("Gemini returned an empty response.")
            return TextGenerationResponse(output_text=output_text)
        except asyncio.CancelledError:
            raise
        except TextGenerationError:
            raise
        except TimeoutError as error:
            raise TextGenerationError("Gemini generation timed out.") from error
        except Exception as error:
            raise TextGenerationError("Gemini generation failed.") from error

    async def aclose(self) -> None:
        """Close Gemini's asynchronous and synchronous transports."""
        try:
            await self._client.aio.aclose()
        finally:
            self._client.close()


__all__ = ["GeminiTextGenerationClient"]

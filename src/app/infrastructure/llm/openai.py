"""OpenAI Responses API adapter for the shared text-generation contract."""

from __future__ import annotations

import asyncio
from typing import Any, cast

from openai import AsyncOpenAI
from openai.types.responses import Response, ResponseTextConfigParam

from app.contracts.messages.llm import TextGenerationRequest, TextGenerationResponse
from app.contracts.ports.llm import ITextGenerationClient, TextGenerationError


class OpenAITextGenerationClient(ITextGenerationClient):
    """Generate plain or strict JSON-schema-constrained text with OpenAI."""

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        timeout_seconds: float = 60.0,
    ) -> None:
        """Create an OpenAI client that owns its SDK connection."""
        if not api_key.strip():
            raise ValueError("OpenAI API key must not be empty.")
        if not model.strip():
            raise ValueError("OpenAI model must not be empty.")
        if timeout_seconds <= 0:
            raise ValueError("OpenAI timeout must be greater than zero.")
        self._client = AsyncOpenAI(api_key=api_key, timeout=timeout_seconds)
        self._model = model.strip()
        self._timeout_seconds = timeout_seconds

    async def generate(self, request: TextGenerationRequest) -> TextGenerationResponse:
        """Call the OpenAI Responses API asynchronously."""
        text_config: ResponseTextConfigParam | None = None
        if request.output_schema is not None:
            text_config = cast(
                ResponseTextConfigParam,
                {
                    "format": {
                        "type": "json_schema",
                        "name": request.schema_name,
                        "schema": request.output_schema,
                        "strict": True,
                    }
                },
            )

        try:
            async with asyncio.timeout(self._timeout_seconds):
                request_kwargs: dict[str, Any] = {
                    "model": self._model,
                    "instructions": request.system_instruction,
                    "input": request.input_text,
                    "max_output_tokens": request.max_output_tokens,
                    "store": False,
                    "stream": False,
                }
                if text_config is not None:
                    request_kwargs["text"] = text_config
                response = await self._client.responses.create(
                    **request_kwargs,
                )
            output_text = cast(Response, response).output_text
            if not output_text.strip():
                raise TextGenerationError("OpenAI returned an empty response.")
            return TextGenerationResponse(output_text=output_text)
        except asyncio.CancelledError:
            raise
        except TextGenerationError:
            raise
        except TimeoutError as error:
            raise TextGenerationError("OpenAI generation timed out.") from error
        except Exception as error:
            raise TextGenerationError("OpenAI generation failed.") from error

    async def aclose(self) -> None:
        """Close OpenAI's asynchronous HTTP transport."""
        await self._client.close()


__all__ = ["OpenAITextGenerationClient"]

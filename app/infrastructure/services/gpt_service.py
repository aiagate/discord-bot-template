import os

from openai import AsyncOpenAI
from openai.types.responses import ResponseInputItemParam
from openai.types.responses.easy_input_message_param import (
    EasyInputMessageParam,
)

from app.core.result import Err, Ok, Result
from app.domain.aggregates.chat_history import ChatMessage, ChatRole
from app.domain.interfaces.ai_service import AIServiceError, IAIService
from app.domain.value_objects.ai_provider import AIProvider


class GptService(IAIService):
    """Implementation of AI service using OpenAI GPT."""

    # SYSTEM_INSTRUCTION moved to database

    @property
    def provider(self) -> AIProvider:
        return AIProvider.GPT

    def __init__(self) -> None:
        """Initialize OpenAI client."""
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            self._client = None
        else:
            self._client = AsyncOpenAI(api_key=api_key)

    async def initialize_ai_agent(self) -> None:
        """Initialize AI agent."""
        # OpenAI doesn't require explicit context caching initialization
        pass

    async def generate_content(
        self,
        prompt: str,
        history: list[ChatMessage],
        system_instruction: str | None = None,
    ) -> Result[str, AIServiceError]:
        """Generate content from prompt using GPT."""
        if not self._client:
            return Err(AIServiceError("OpenAI API key not configured."))

        try:
            gpt_history: list[ResponseInputItemParam] = [
                EasyInputMessageParam(
                    role="user" if msg.role == ChatRole.USER else "system",
                    content=msg.content,
                    type="message",
                )
                for msg in history
            ]
            gpt_history.append(
                EasyInputMessageParam(role="user", content=prompt, type="message")
            )

            response = await self._client.responses.create(
                model="gpt-4o-mini",
                instructions=system_instruction or "You are a helpful assistant.",
                input=gpt_history,
                store=False,
            )

            return Ok(response.output_text)

        except Exception as e:
            return Err(AIServiceError(f"OpenAI API Error: {str(e)}"))

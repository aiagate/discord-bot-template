from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.result import Err, Ok
from app.domain.aggregates.chat_history import ChatMessage, ChatRole
from app.domain.value_objects.sent_at import SentAt
from app.infrastructure.services.gpt_service import GptService


class TestGptService:
    @pytest.fixture
    def mock_openai_client(self, mocker: Any) -> Any:
        mock_client = mocker.patch(
            "app.infrastructure.services.gpt_service.AsyncOpenAI", autospec=True
        )
        # Setup async accessors
        mock_client.return_value.responses = MagicMock()
        mock_client.return_value.responses.create = AsyncMock()
        return mock_client

    @pytest.mark.asyncio
    async def test_generate_content_success(
        self, mock_openai_client: Any, mocker: Any
    ) -> None:
        # Arrange
        mocker.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"})
        service = GptService()
        service._client = mock_openai_client.return_value

        mock_response = MagicMock()
        mock_response.output_text = "Response Content"
        service._client.responses.create.return_value = mock_response

        history = [
            ChatMessage.create(
                role=ChatRole.USER,
                content="Hello",
                sent_at=SentAt(datetime.now(UTC)),
            )
        ]

        # Act
        result = await service.generate_content("prompt", history)

        # Assert
        assert isinstance(result, Ok)
        assert result.value == "Response Content"

        service._client.responses.create.assert_called_once()
        call_args = service._client.responses.create.call_args
        assert call_args.kwargs["model"] == "gpt-4o-mini"
        assert call_args.kwargs["instructions"] == "You are a helpful assistant."
        assert call_args.kwargs["store"] is False

        input_msgs = call_args.kwargs["input"]
        # History + Prompt
        assert len(input_msgs) == 2
        assert input_msgs[0]["content"] == "Hello"
        assert input_msgs[1]["content"] == "prompt"

    @pytest.mark.asyncio
    async def test_generate_content_api_error(
        self, mock_openai_client: Any, mocker: Any
    ) -> None:
        # Arrange
        mocker.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"})
        service = GptService()
        service._client = mock_openai_client.return_value

        service._client.responses.create.side_effect = Exception("API Error")

        # Act
        result = await service.generate_content("prompt", [])

        # Assert
        assert isinstance(result, Err)
        assert "API Error" in str(result.error)

    @pytest.mark.asyncio
    async def test_initialize_ai_agent_does_nothing(
        self, mock_openai_client: Any, mocker: Any
    ) -> None:
        # Arrange
        mocker.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"})
        service = GptService()
        service._client = mock_openai_client.return_value

        # Act
        await service.initialize_ai_agent()

        # Assert
        # Nothing to assert really, just ensuring it doesn't crash

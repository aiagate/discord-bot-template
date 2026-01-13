from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.infrastructure.services.gemini_service import GeminiService


class TestGeminiService:
    @pytest.fixture
    def mock_genai_client(self, mocker: Any) -> Any:
        mock_client = mocker.patch(
            "app.infrastructure.services.gemini_service.genai.Client", autospec=True
        )
        # Setup async accessors
        mock_client.return_value.aio = MagicMock()
        mock_client.return_value.aio.chats = MagicMock()
        mock_client.return_value.aio.chats.create = MagicMock()
        mock_client.return_value.aio.caches = MagicMock()
        mock_client.return_value.aio.caches.list = MagicMock()
        mock_client.return_value.aio.caches.create = AsyncMock()
        return mock_client

    # @pytest.mark.asyncio
    # async def test_initialize_ai_agent_creates_cache_if_not_exists(
    #     self, mock_genai_client: Any
    # ) -> None:
    #     # Arrange
    #     service = GeminiService()
    #     mock_client_instance = mock_genai_client.return_value

    #     class AsyncIterator:
    #         def __init__(self, items: list[Any]) -> None:
    #             self.items = items

    #         def __aiter__(self) -> "AsyncIterator":
    #             self._iter = iter(self.items)
    #             return self

    #         async def __anext__(self) -> Any:
    #             try:
    #                 return next(self._iter)
    #             except StopIteration as e:
    #                 raise StopAsyncIteration from e

    #     # Mock list() to be an AsyncMock that returns an AsyncIterator
    #     # This satisfies `await self._client.aio.caches.list()`
    #     mock_client_instance.aio.caches.list = AsyncMock()
    #     mock_client_instance.aio.caches.list.return_value = AsyncIterator([])

    #     mock_created_cache = MagicMock()
    #     mock_created_cache.name = "created_cache_name"
    #     mock_client_instance.aio.caches.create.return_value = mock_created_cache

    #     # Act
    #     await service.initialize_ai_agent()

    #     # Assert
    #     assert service._cache_name == "created_cache_name"
    #     mock_client_instance.aio.caches.create.assert_called_once()
    #     call_args = mock_client_instance.aio.caches.create.call_args
    #     assert call_args.kwargs["model"] == "gemini-3-flash-preview"
    #     assert call_args.kwargs["config"].display_name == "Dorothy System Instructions"

    # @pytest.mark.asyncio
    # async def test_initialize_ai_agent_uses_existing_cache(
    #     self, mock_genai_client: Any
    # ) -> None:
    #     # Arrange
    #     service = GeminiService()
    #     mock_client_instance = mock_genai_client.return_value

    #     mock_cache = MagicMock()
    #     mock_cache.display_name = "Dorothy System Instructions"
    #     mock_cache.name = "existing_cache_name"

    #     class AsyncIterator:
    #         def __init__(self, items: list[Any]) -> None:
    #             self.items = items

    #         def __aiter__(self) -> "AsyncIterator":
    #             self._iter = iter(self.items)
    #             return self

    #         async def __anext__(self) -> Any:
    #             try:
    #                 return next(self._iter)
    #             except StopIteration as e:
    #                 raise StopAsyncIteration from e

    #     mock_client_instance.aio.caches.list = AsyncMock()
    #     mock_client_instance.aio.caches.list.return_value = AsyncIterator([mock_cache])

    #     # Act
    #     await service.initialize_ai_agent()

    #     # Assert
    #     assert service._cache_name == "existing_cache_name"
    #     mock_client_instance.aio.caches.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_generate_content_uses_cache_if_initialized(
        self, mock_genai_client: Any, mocker: Any
    ) -> None:
        # Arrange
        mocker.patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"})
        service = GeminiService()
        # Manually set the mocked client because GeminiService() creates a real client with the key
        service._client = mock_genai_client.return_value

        service._cache_name = "test_cache_name"  # Simulate initialized
        mock_client_instance = mock_genai_client.return_value

        mock_chat = MagicMock()
        mock_chat.send_message = AsyncMock()
        mock_chat.send_message.return_value.text = "Hello"
        mock_client_instance.aio.chats.create.return_value = mock_chat

        # Act
        await service.generate_content("prompt", [])

        # Assert
        mock_client_instance.aio.chats.create.assert_called_once()
        config = mock_client_instance.aio.chats.create.call_args.kwargs["config"]
        assert config.cached_content == "test_cache_name"

        # Check if system_instruction is None or missing
        assert getattr(config, "system_instruction", None) is None

    @pytest.mark.asyncio
    async def test_generate_content_uses_system_instruction_if_cache_not_initialized(
        self, mock_genai_client: Any, mocker: Any
    ) -> None:
        # Arrange
        mocker.patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"})
        service = GeminiService()
        # Manually set the mocked client or ensure it's using the one we expect if checking calls on mock_genai_client
        service._client = mock_genai_client.return_value

        service._cache_name = None  # Not initialized
        mock_client_instance = mock_genai_client.return_value

        mock_chat = MagicMock()
        mock_chat.send_message = AsyncMock()
        mock_chat.send_message.return_value.text = "Hello"
        mock_client_instance.aio.chats.create.return_value = mock_chat

        # Act
        await service.generate_content("prompt", [], system_instruction="You are a bot")

        # Assert
        mock_client_instance.aio.chats.create.assert_called_once()
        config = mock_client_instance.aio.chats.create.call_args.kwargs["config"]
        assert not hasattr(config, "cached_content") or config.cached_content is None
        assert config.system_instruction == "You are a bot"

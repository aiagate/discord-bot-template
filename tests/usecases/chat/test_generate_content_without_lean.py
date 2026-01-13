from unittest.mock import AsyncMock, Mock

import pytest

from app.core.result import Err, Ok, is_err
from app.domain.aggregates.chat_history import ChatMessage
from app.domain.interfaces.ai_service import IAIService
from app.domain.repositories import IUnitOfWork
from app.domain.value_objects import AIProvider
from app.usecases.chat.generate_content_without_lean import (
    GenerateContentWithoutLeanHandler,
    GenerateContentWithoutLeanQuery,
)


@pytest.fixture
def mock_ai_service() -> IAIService:
    service = Mock(spec=IAIService)
    service.generate_content = AsyncMock(return_value=Ok("Generated Content"))
    service.provider = AIProvider.GEMINI
    return service


@pytest.mark.anyio
async def test_generate_content_without_lean_success(
    uow: IUnitOfWork, mock_ai_service: IAIService
):
    """Test successful content generation without lean (no history saving)."""
    handler = GenerateContentWithoutLeanHandler(mock_ai_service, uow)
    prompt = "Hello AI"

    # Execute
    query = GenerateContentWithoutLeanQuery(prompt=prompt)
    result = await handler.handle(query)

    assert not is_err(result)
    assert result.unwrap() == "Generated Content"

    # Verify interactions
    mock_ai_service.generate_content.assert_called_once()  # type: ignore

    # Verify NO new messages added to DB
    async with uow:
        messages = (
            await uow.GetRepository(ChatMessage).get_recent_history(100)
        ).unwrap()
        assert len(messages) == 0


@pytest.mark.anyio
async def test_generate_content_without_lean_ai_failure(
    uow: IUnitOfWork, mock_ai_service: IAIService
):
    """Test AI service failure."""
    mock_ai_service.generate_content.return_value = Err("AI Error")  # type: ignore
    handler = GenerateContentWithoutLeanHandler(mock_ai_service, uow)

    result = await handler.handle(GenerateContentWithoutLeanQuery(prompt="Prompt"))

    assert is_err(result)
    assert "Failed to generate content" in result.error.message


@pytest.mark.anyio
async def test_generate_content_without_lean_history_failure(
    uow: IUnitOfWork, mock_ai_service: IAIService
):
    """Test history retrieval failure."""
    mock_uow = Mock(spec=IUnitOfWork)
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=None)

    mock_repo = Mock()
    mock_repo.get_recent_history = AsyncMock(return_value=Err("DB Error"))

    mock_uow.GetRepository.return_value = mock_repo

    handler = GenerateContentWithoutLeanHandler(mock_ai_service, mock_uow)

    result = await handler.handle(GenerateContentWithoutLeanQuery(prompt="Prompt"))

    assert is_err(result)
    assert "Failed to retrieve chat history" in result.error.message

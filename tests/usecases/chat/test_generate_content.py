from unittest.mock import AsyncMock, Mock

import pytest

from app.core.result import Err, Ok, is_err
from app.domain.aggregates.chat_history import ChatMessage
from app.domain.aggregates.system_instruction import SystemInstruction
from app.domain.interfaces.ai_service import IAIService
from app.domain.repositories import IUnitOfWork
from app.domain.value_objects import AIProvider
from app.usecases.chat.generate_content import (
    GenerateContentHandler,
    GenerateContentQuery,
)


@pytest.fixture
def mock_ai_service() -> IAIService:
    service = Mock(spec=IAIService)
    service.generate_content = AsyncMock(return_value=Ok("Generated Content"))
    service.provider = AIProvider.GEMINI
    return service


@pytest.mark.anyio
async def test_generate_content_success(uow: IUnitOfWork, mock_ai_service: IAIService):
    """Test successful content generation."""
    handler = GenerateContentHandler(mock_ai_service, uow)
    prompt = "Hello AI"

    # Setup active instruction
    instruction = SystemInstruction.create(
        AIProvider.GEMINI, "You are a bot", is_active=True
    ).unwrap()
    async with uow:
        await uow.GetRepository(SystemInstruction).save(instruction)
        await uow.commit()

    # Execute
    query = GenerateContentQuery(prompt=prompt)
    result = await handler.handle(query)

    assert not is_err(result)
    assert result.unwrap() == "Generated Content"

    # Verify interactions
    mock_ai_service.generate_content.assert_called_once()  # type: ignore
    call_args = mock_ai_service.generate_content.call_args  # type: ignore
    assert call_args[0][0] == prompt
    assert len(call_args[0][1]) == 0
    assert call_args[1]["system_instruction"] == "You are a bot"

    # Verify messages saved
    async with uow:
        messages = (
            await uow.GetRepository(ChatMessage).get_recent_history(10)
        ).unwrap()
        assert len(messages) == 2


@pytest.mark.anyio
async def test_generate_content_ai_failure(
    uow: IUnitOfWork, mock_ai_service: IAIService
):
    """Test AI service failure."""
    mock_ai_service.generate_content.return_value = Err("AI Error")  # type: ignore
    handler = GenerateContentHandler(mock_ai_service, uow)

    result = await handler.handle(GenerateContentQuery(prompt="Prompt"))

    assert is_err(result)
    assert "Failed to generate content" in result.error.message

    # Verify no messages saved
    async with uow:
        messages = (
            await uow.GetRepository(ChatMessage).get_recent_history(10)
        ).unwrap()
        assert len(messages) == 0


@pytest.mark.anyio
async def test_generate_content_history_failure(
    uow: IUnitOfWork, mock_ai_service: IAIService
):
    """Test history retrieval failure."""
    # We can't easily mock the repository method on the real uow without patching.
    # Instead, we can mock the uow itself for this specific test,
    # or rely on the fact that existing uow works and we want to simulate an error.

    # Option 2: Mock uow
    mock_uow = Mock(spec=IUnitOfWork)
    # Context manager mock
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=None)

    mock_repo = Mock()
    mock_repo.get_recent_history = AsyncMock(return_value=Err("DB Error"))

    mock_uow.GetRepository.return_value = mock_repo

    handler = GenerateContentHandler(mock_ai_service, mock_uow)

    result = await handler.handle(GenerateContentQuery(prompt="Prompt"))

    assert is_err(result)
    assert "Failed to retrieve chat history" in result.error.message

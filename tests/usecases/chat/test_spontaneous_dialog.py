from unittest.mock import AsyncMock, Mock

import pytest

from app.core.result import Err, Ok, is_err
from app.domain.interfaces.ai_service import IAIService
from app.domain.repositories import IUnitOfWork
from app.domain.value_objects import AIProvider
from app.usecases.chat.spontaneous_dialog import (
    TARGET_CHANNEL_ID,
    SpontaneousDialogCommand,
    SpontaneousDialogHandler,
)


@pytest.fixture
def mock_ai_service() -> IAIService:
    service = Mock(spec=IAIService)
    service.generate_content = AsyncMock(return_value=Ok("Spontaneous Message"))
    service.provider = AIProvider.GEMINI
    return service


@pytest.mark.anyio
async def test_spontaneous_dialog_success(
    uow: IUnitOfWork, mock_ai_service: IAIService
):
    """Test successful spontaneous dialog trigger."""
    handler = SpontaneousDialogHandler(mock_ai_service, uow)

    command = SpontaneousDialogCommand()
    result = await handler.handle(command)

    assert not is_err(result)
    content, channel_id = result.unwrap()

    assert content == "Spontaneous Message"
    assert channel_id == TARGET_CHANNEL_ID

    # Verify AI service called
    mock_ai_service.generate_content.assert_called_once()  # type: ignore
    call_args = mock_ai_service.generate_content.call_args  # type: ignore
    # First arg is internal prompt
    assert "あなたはおしゃべりがしたい気分です" in call_args[0][0]


@pytest.mark.anyio
async def test_spontaneous_dialog_ai_failure(
    uow: IUnitOfWork, mock_ai_service: IAIService
):
    """Test AI service failure."""
    mock_ai_service.generate_content.return_value = Err("AI Error")  # type: ignore
    handler = SpontaneousDialogHandler(mock_ai_service, uow)

    result = await handler.handle(SpontaneousDialogCommand())

    assert is_err(result)
    assert "Failed to generate content" in result.error.message


@pytest.mark.anyio
async def test_spontaneous_dialog_history_failure(
    uow: IUnitOfWork, mock_ai_service: IAIService
):
    """Test history retrieval failure."""
    mock_uow = Mock(spec=IUnitOfWork)
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=None)

    mock_repo = Mock()
    mock_repo.get_recent_history = AsyncMock(return_value=Err("DB Error"))

    mock_uow.GetRepository.return_value = mock_repo

    handler = SpontaneousDialogHandler(mock_ai_service, mock_uow)

    result = await handler.handle(SpontaneousDialogCommand())

    assert is_err(result)
    assert "Failed to retrieve chat history" in result.error.message

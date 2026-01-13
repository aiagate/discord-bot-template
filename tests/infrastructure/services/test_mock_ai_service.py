import pytest

from app.core.result import Ok
from app.domain.value_objects.ai_provider import AIProvider
from app.infrastructure.services.mock_ai_service import MockAIService


@pytest.mark.asyncio
async def test_mock_ai_service_initialization():
    service = MockAIService()
    assert service.provider == AIProvider.MOCK


@pytest.mark.asyncio
async def test_mock_ai_service_generate_content():
    service = MockAIService()
    result = await service.generate_content("Test Prompt", [])

    assert isinstance(result, Ok)
    assert result.value == "This is a mock response from MockAIService."


@pytest.mark.asyncio
async def test_mock_ai_service_initialize_ai_agent():
    service = MockAIService()
    # Should not raise any exception
    await service.initialize_ai_agent()

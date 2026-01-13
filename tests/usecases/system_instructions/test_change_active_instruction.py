from unittest.mock import AsyncMock, Mock

import pytest

from app.core.result import Err, is_err
from app.domain.aggregates.system_instruction import SystemInstruction
from app.domain.repositories import IUnitOfWork
from app.domain.repositories.interfaces import RepositoryError, RepositoryErrorType
from app.domain.value_objects.ai_provider import AIProvider
from app.domain.value_objects.system_instruction_id import SystemInstructionId
from app.usecases.system_instructions.change_active_instruction import (
    ChangeActiveSystemInstruction,
)


@pytest.mark.anyio
async def test_change_active_instruction(uow: IUnitOfWork):
    """Test switching active system instruction."""
    handler = ChangeActiveSystemInstruction(uow)

    # 1. Create two instructions
    res1 = SystemInstruction.create(AIProvider.GEMINI, "Instruction 1", is_active=True)
    assert not is_err(res1)
    instr1 = res1.unwrap()

    res2 = SystemInstruction.create(AIProvider.GEMINI, "Instruction 2", is_active=False)
    assert not is_err(res2)
    instr2 = res2.unwrap()

    async with uow:
        repo = uow.GetRepository(SystemInstruction)
        await repo.save(instr1)
        await repo.save(instr2)
        await uow.commit()

    # Verify initial state
    async with uow:
        repo = uow.GetRepository(SystemInstruction)
        fetched_instr1 = (await repo.find_by_id(instr1.id)).unwrap()
        fetched_instr2 = (await repo.find_by_id(instr2.id)).unwrap()
        assert fetched_instr1 is not None
        assert fetched_instr2 is not None
        assert fetched_instr1.is_active
        assert not fetched_instr2.is_active

    # 2. Switch to Instruction 2
    result = await handler.execute(instr2.id)
    assert not is_err(result)

    # Verify final state
    async with uow:
        repo = uow.GetRepository(SystemInstruction)
        fetched_instr1 = (await repo.find_by_id(instr1.id)).unwrap()
        fetched_instr2 = (await repo.find_by_id(instr2.id)).unwrap()
        assert fetched_instr1 is not None
        assert fetched_instr2 is not None
        assert not fetched_instr1.is_active
        assert fetched_instr2.is_active


@pytest.mark.anyio
async def test_change_active_instruction_not_found(uow: IUnitOfWork):
    """Test trying to activate non-existent instruction."""
    handler = ChangeActiveSystemInstruction(uow)

    # Generate random ID
    id_res = SystemInstructionId.generate()
    assert not is_err(id_res)
    random_id = id_res.unwrap()

    result = await handler.execute(random_id)

    assert is_err(result)
    assert "not found" in str(result.error)


@pytest.mark.anyio
async def test_change_active_instruction_repo_error(uow: IUnitOfWork):
    """Test repository error during fetch."""
    mock_uow = Mock(spec=IUnitOfWork)
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=None)

    mock_repo = Mock()
    error = RepositoryError(RepositoryErrorType.UNEXPECTED, "DB Connection Fail")
    mock_repo.find_by_id = AsyncMock(return_value=Err(error))

    mock_uow.GetRepository.return_value = mock_repo

    handler = ChangeActiveSystemInstruction(mock_uow)

    # Generate random ID
    id_res = SystemInstructionId.generate()
    assert not is_err(id_res)
    random_id = id_res.unwrap()

    result = await handler.execute(random_id)

    assert is_err(result)
    assert "DB Connection Fail" in str(result.error)

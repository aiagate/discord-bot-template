"""Tests for source-safe asynchronous memory consolidation."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from flow_res import Err, Ok, is_err, is_ok

from app.contracts.messages.user_memory import (
    UserMemoryContext,
    UserMemoryExtractionResult,
    UserMemoryProfilePatch,
    UserMemorySource,
    UserMemorySourceEvaluation,
    UserMemoryTimelinePatch,
)
from app.contracts.ports import (
    IUserMemoryExtractor,
    IUserMemorySourceStore,
    IUserMemoryStore,
    MemoryExtractionError,
)
from app.usecases.memory.consolidate_user_memory import (
    ConsolidateUserMemoryCommand,
    ConsolidateUserMemoryHandler,
)


def _source(
    message_id: str, occurred_at: datetime, *, author_kind: str = "user"
) -> UserMemorySource:
    """Create a source for a single user/day batch."""
    return UserMemorySource(
        message_id=message_id,
        user_id="01USER",
        platform="DISCORD",
        author_kind=author_kind,
        external_sender_id="alice",
        content=message_id,
        occurred_at=occurred_at,
    )


@pytest.mark.anyio
async def test_consolidation_marks_only_evaluated_sources_after_writes() -> None:
    """Keep deferred sources retryable while applying cited patches."""
    sources = (
        _source("source-1", datetime(2026, 9, 11, 1, tzinfo=UTC)),
        _source("source-2", datetime(2026, 9, 11, 2, tzinfo=UTC)),
    )
    source_store = MagicMock(spec=IUserMemorySourceStore)
    source_store.list_pending = AsyncMock(return_value=Ok(list(sources)))
    source_store.mark_processed = AsyncMock(return_value=Ok(None))
    memory_store = MagicMock(spec=IUserMemoryStore)
    memory_store.get_context = AsyncMock(return_value=Ok(UserMemoryContext()))
    memory_store.apply = AsyncMock(return_value=Ok(None))
    extractor = MagicMock(spec=IUserMemoryExtractor)
    extractor.extract = AsyncMock(
        return_value=Ok(
            UserMemoryExtractionResult(
                profile_patch=UserMemoryProfilePatch(
                    summary="朝に作業する",
                    traits=["計画的"],
                    preferences=[],
                    confidence=0.9,
                    source_message_ids=["source-1"],
                ),
                timeline_patches=[
                    UserMemoryTimelinePatch(
                        title="作業方針",
                        summary="朝に作業する方針を確認した。",
                        source_message_ids=["source-1"],
                        confidence=0.8,
                    )
                ],
                source_evaluations=[
                    UserMemorySourceEvaluation(
                        message_id="source-1", disposition="used"
                    ),
                    UserMemorySourceEvaluation(
                        message_id="source-2", disposition="deferred"
                    ),
                ],
            )
        )
    )
    handler = ConsolidateUserMemoryHandler(source_store, memory_store, extractor)

    result = await handler.handle(
        ConsolidateUserMemoryCommand(
            reference_time=datetime(2026, 9, 12, 0, tzinfo=UTC)
        )
    )

    assert is_ok(result)
    assert result.value.evaluated_source_count == 1
    assert result.value.deferred_source_count == 1
    memory_store.apply.assert_awaited_once()
    source_store.mark_processed.assert_awaited_once_with(
        ("source-1",), processed_at=datetime(2026, 9, 12, tzinfo=UTC)
    )


@pytest.mark.anyio
async def test_consolidation_does_not_mark_sources_when_extraction_fails() -> None:
    """Leave raw sources pending when the external extractor fails."""
    source = _source("source-1", datetime(2026, 9, 11, 1, tzinfo=UTC))
    source_store = MagicMock(spec=IUserMemorySourceStore)
    source_store.list_pending = AsyncMock(return_value=Ok([source]))
    source_store.mark_processed = AsyncMock(return_value=Ok(None))
    memory_store = MagicMock(spec=IUserMemoryStore)
    memory_store.get_context = AsyncMock(return_value=Ok(UserMemoryContext()))
    extractor = MagicMock(spec=IUserMemoryExtractor)
    extractor.extract = AsyncMock(
        return_value=Err(MemoryExtractionError(message="temporary failure"))
    )
    handler = ConsolidateUserMemoryHandler(source_store, memory_store, extractor)

    result = await handler.handle(
        ConsolidateUserMemoryCommand(reference_time=datetime(2026, 9, 12, tzinfo=UTC))
    )

    assert is_err(result)
    source_store.mark_processed.assert_not_awaited()
    memory_store.apply.assert_not_awaited()


@pytest.mark.anyio
async def test_consolidation_rejects_bot_messages_as_memory_evidence() -> None:
    """Do not project a bot response into the owner's Profile or Timeline."""
    sources = (
        _source("source-1", datetime(2026, 9, 11, 1, tzinfo=UTC)),
        _source(
            "source-2",
            datetime(2026, 9, 11, 2, tzinfo=UTC),
            author_kind="bot",
        ),
    )
    source_store = MagicMock(spec=IUserMemorySourceStore)
    source_store.list_pending = AsyncMock(return_value=Ok(list(sources)))
    source_store.mark_processed = AsyncMock(return_value=Ok(None))
    memory_store = MagicMock(spec=IUserMemoryStore)
    memory_store.get_context = AsyncMock(return_value=Ok(UserMemoryContext()))
    memory_store.apply = AsyncMock(return_value=Ok(None))
    extractor = MagicMock(spec=IUserMemoryExtractor)
    extractor.extract = AsyncMock(
        return_value=Ok(
            UserMemoryExtractionResult(
                profile_patch=None,
                timeline_patches=[
                    UserMemoryTimelinePatch(
                        title="bot response",
                        summary="bot response",
                        source_message_ids=["source-2"],
                        confidence=0.9,
                    )
                ],
                source_evaluations=[
                    UserMemorySourceEvaluation(
                        message_id=source.message_id, disposition="used"
                    )
                    for source in sources
                ],
            )
        )
    )
    handler = ConsolidateUserMemoryHandler(source_store, memory_store, extractor)

    result = await handler.handle(
        ConsolidateUserMemoryCommand(
            reference_time=datetime(2026, 9, 12, 0, tzinfo=UTC)
        )
    )

    assert is_err(result)
    memory_store.apply.assert_not_awaited()
    source_store.mark_processed.assert_not_awaited()

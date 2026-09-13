"""Consolidate completed raw chat into user Profile and Timeline views."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from flow_med import Request, RequestHandler
from flow_res import Err, Ok, Result, is_err
from injector import inject

from app.contracts.messages.user_memory import (
    UserMemoryExtractionRequest,
    UserMemorySource,
)
from app.contracts.ports.user_memory import (
    IUserMemoryExtractor,
    IUserMemorySourceStore,
    IUserMemoryStore,
)
from app.usecases.result import ErrorType, UseCaseError, UseCaseResultError

logger = logging.getLogger(__name__)
JST = ZoneInfo("Asia/Tokyo")
SOURCE_LIMIT = 500
SOURCES_PER_BATCH = 100


@dataclass(frozen=True, slots=True)
class ConsolidateUserMemoryResult:
    """Summary of one consolidation run."""

    batch_count: int
    evaluated_source_count: int
    deferred_source_count: int
    profile_update_count: int
    timeline_update_count: int


@dataclass(frozen=True, slots=True)
class ConsolidateUserMemoryCommand(
    Request[Result[ConsolidateUserMemoryResult, UseCaseResultError]]
):
    """Consolidate mapped raw chat before the current JST day."""

    reference_time: datetime | None = None


def _as_utc(value: datetime) -> datetime:
    """Normalize a scheduling timestamp and reject naive values."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Reference time must be timezone-aware.")
    return value.astimezone(UTC)


def _day(source: UserMemorySource) -> str:
    """Return the source's consolidation day in Japan Standard Time."""
    return source.occurred_at.astimezone(JST).date().isoformat()


def _validate_extraction(
    result: object,
    sources: tuple[UserMemorySource, ...],
) -> None:
    """Ensure the extractor evaluated only the current batch's source IDs."""
    source_ids = {source.message_id for source in sources}
    user_source_ids = {
        source.message_id for source in sources if source.author_kind == "user"
    }
    evaluations = getattr(result, "source_evaluations", ())
    evaluation_ids = [evaluation.message_id for evaluation in evaluations]
    if set(evaluation_ids) != source_ids or len(evaluation_ids) != len(source_ids):
        raise ValueError("Memory extraction must evaluate every source exactly once.")
    used_ids = {
        evaluation.message_id
        for evaluation in evaluations
        if evaluation.disposition == "used"
    }
    profile_patch = getattr(result, "profile_patch", None)
    if profile_patch is not None and profile_patch.update_mode != "defer":
        if not set(profile_patch.source_message_ids) <= used_ids:
            raise ValueError("Profile patch must cite used source IDs.")
        if not set(profile_patch.source_message_ids) <= user_source_ids:
            raise ValueError("Profile patch must cite user-authored source IDs.")
    for patch in getattr(result, "timeline_patches", ()):
        if not set(patch.source_message_ids) <= used_ids:
            raise ValueError("Timeline patch must cite used source IDs.")
        if not set(patch.source_message_ids) <= user_source_ids:
            raise ValueError("Timeline patch must cite user-authored source IDs.")


class ConsolidateUserMemoryHandler(
    RequestHandler[
        ConsolidateUserMemoryCommand,
        Result[ConsolidateUserMemoryResult, UseCaseResultError],
    ]
):
    """Apply conservative LLM patches and then mark successful raw sources."""

    @inject
    def __init__(
        self,
        source_store: IUserMemorySourceStore,
        memory_store: IUserMemoryStore,
        extractor: IUserMemoryExtractor,
    ) -> None:
        self._source_store = source_store
        self._memory_store = memory_store
        self._extractor = extractor

    async def handle(
        self, request: ConsolidateUserMemoryCommand
    ) -> Result[ConsolidateUserMemoryResult, UseCaseResultError]:
        """Consolidate eligible sources without marking deferred inputs."""
        try:
            reference_time = _as_utc(request.reference_time or datetime.now(UTC))
            pending_result = await self._source_store.list_pending(
                reference_time=reference_time,
                limit=SOURCE_LIMIT,
            )
            if is_err(pending_result):
                return Err(pending_result.error)
            grouped: dict[tuple[str, str], list[UserMemorySource]] = defaultdict(list)
            for source in pending_result.value:
                grouped[(source.user_id, _day(source))].append(source)

            evaluated_count = 0
            deferred_count = 0
            profile_count = 0
            timeline_count = 0
            batch_count = 0
            for (user_id, day), grouped_sources in sorted(grouped.items()):
                for offset in range(0, len(grouped_sources), SOURCES_PER_BATCH):
                    sources = tuple(
                        grouped_sources[offset : offset + SOURCES_PER_BATCH]
                    )
                    context_result = await self._memory_store.get_context(user_id)
                    if is_err(context_result):
                        return Err(context_result.error)
                    extraction = await self._extractor.extract(
                        UserMemoryExtractionRequest(
                            user_id=user_id,
                            day=day,
                            raw_logs=list(sources),
                            existing_profile=context_result.value.profile,
                            existing_timeline=list(context_result.value.timeline),
                        )
                    )
                    if is_err(extraction):
                        return Err(
                            UseCaseError(
                                type=ErrorType.UNEXPECTED,
                                message=str(extraction.error),
                            )
                        )
                    _validate_extraction(extraction.value, sources)
                    applied = await self._memory_store.apply(
                        user_id=user_id,
                        profile_patch=extraction.value.profile_patch,
                        timeline_patches=tuple(extraction.value.timeline_patches),
                        source_messages=sources,
                        reference_time=reference_time,
                        day=day,
                    )
                    if is_err(applied):
                        return Err(applied.error)
                    evaluated_ids = tuple(
                        evaluation.message_id
                        for evaluation in extraction.value.source_evaluations
                        if evaluation.disposition in {"used", "not_memorable"}
                    )
                    marked = await self._source_store.mark_processed(
                        evaluated_ids, processed_at=reference_time
                    )
                    if is_err(marked):
                        return Err(marked.error)
                    evaluated_count += len(evaluated_ids)
                    deferred_count += len(sources) - len(evaluated_ids)
                    profile_count += int(
                        extraction.value.profile_patch is not None
                        and extraction.value.profile_patch.update_mode != "defer"
                    )
                    timeline_count += len(extraction.value.timeline_patches)
                    batch_count += 1
            return Ok(
                ConsolidateUserMemoryResult(
                    batch_count=batch_count,
                    evaluated_source_count=evaluated_count,
                    deferred_source_count=deferred_count,
                    profile_update_count=profile_count,
                    timeline_update_count=timeline_count,
                )
            )
        except Exception as error:
            logger.exception("User memory consolidation failed")
            return Err(
                UseCaseError(
                    type=ErrorType.UNEXPECTED,
                    message=f"User memory consolidation failed: {error}",
                )
            )

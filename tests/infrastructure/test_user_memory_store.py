"""Tests for user-scoped Profile and Timeline Markdown storage."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from flow_res import is_ok

from app.contracts.messages.user_memory import (
    UserMemoryProfilePatch,
    UserMemorySource,
    UserMemoryTimelinePatch,
)
from app.infrastructure.memory.user_memory_store import MarkdownUserMemoryStore


def _source(message_id: str, user_id: str = "01USER") -> UserMemorySource:
    """Create one test source row."""
    return UserMemorySource(
        message_id=message_id,
        user_id=user_id,
        platform="DISCORD",
        author_kind="user",
        external_sender_id="discord-user",
        content="朝に作業する",
        occurred_at=datetime(2026, 9, 11, 1, 0, tzinfo=UTC),
    )


@pytest.mark.anyio
async def test_profile_and_timeline_are_scoped_and_idempotent(tmp_path: Path) -> None:
    """Persist both views and read the same result after a repeated apply."""
    store = MarkdownUserMemoryStore(tmp_path)
    source = _source("01MESSAGE")
    profile = UserMemoryProfilePatch(
        summary="朝型の利用者",
        traits=["計画的"],
        preferences=["朝に作業"],
        confidence=0.9,
        source_message_ids=[source.message_id],
    )
    timeline = UserMemoryTimelinePatch(
        title="作業時間の相談",
        summary="朝に作業する方針を確認した。",
        source_message_ids=[source.message_id],
        confidence=0.8,
    )
    reference_time = datetime(2026, 9, 12, tzinfo=UTC)

    first = await store.apply(
        user_id=source.user_id,
        profile_patch=profile,
        timeline_patches=(timeline,),
        source_messages=(source,),
        reference_time=reference_time,
        day="2026-09-11",
    )
    second = await store.apply(
        user_id=source.user_id,
        profile_patch=profile,
        timeline_patches=(timeline,),
        source_messages=(source,),
        reference_time=reference_time,
        day="2026-09-11",
    )

    assert is_ok(first)
    assert is_ok(second)
    context_result = await store.get_context(source.user_id)
    assert is_ok(context_result)
    assert context_result.value.profile is not None
    assert context_result.value.profile.summary == "朝型の利用者"
    assert context_result.value.profile.preferences == ("朝に作業",)
    assert context_result.value.profile.confidence == 0.9
    assert context_result.value.profile.created_at == reference_time
    assert len(context_result.value.timeline) == 1
    assert context_result.value.timeline[0].user_id == source.user_id
    assert (tmp_path / source.user_id / "profile.md").exists()


@pytest.mark.anyio
async def test_profile_replace_and_deferred_patch_do_not_leak_between_users(
    tmp_path: Path,
) -> None:
    """Replace only the owner's profile and ignore deferred changes."""
    store = MarkdownUserMemoryStore(tmp_path)
    source = _source("01MESSAGE")
    reference_time = datetime(2026, 9, 12, tzinfo=UTC)
    saved = await store.apply(
        user_id=source.user_id,
        profile_patch=UserMemoryProfilePatch(
            summary="最初",
            traits=["A"],
            preferences=["B"],
            confidence=0.8,
            source_message_ids=[source.message_id],
        ),
        timeline_patches=(),
        source_messages=(source,),
        reference_time=reference_time,
        day="2026-09-11",
    )
    assert is_ok(saved)

    replaced = await store.apply(
        user_id=source.user_id,
        profile_patch=UserMemoryProfilePatch(
            summary="訂正後",
            traits=["C"],
            preferences=[],
            confidence=0.95,
            source_message_ids=[source.message_id],
            update_mode="replace",
        ),
        timeline_patches=(),
        source_messages=(source,),
        reference_time=reference_time,
        day="2026-09-11",
    )
    assert is_ok(replaced)

    deferred = await store.apply(
        user_id=source.user_id,
        profile_patch=UserMemoryProfilePatch(
            summary="保存しない",
            traits=["D"],
            preferences=[],
            confidence=0.1,
            source_message_ids=[source.message_id],
            update_mode="defer",
        ),
        timeline_patches=(),
        source_messages=(source,),
        reference_time=reference_time,
        day="2026-09-11",
    )
    assert is_ok(deferred)

    context_result = await store.get_context(source.user_id)
    other_result = await store.get_context("02OTHER")
    assert is_ok(context_result)
    assert is_ok(other_result)
    assert context_result.value.profile is not None
    assert context_result.value.profile.summary == "訂正後"
    assert context_result.value.profile.traits == ("C",)
    assert other_result.value.profile is None

"""Tests for Markdown and YAML-frontmatter character memory storage."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from flow_res import is_err, is_ok

from app.domain.character_memory import CharacterMemory, CharacterMemorySummary
from app.infrastructure.memory import MarkdownCharacterMemoryStore


def _memory(
    source: str,
    *,
    character: str = "dorothy",
    sequence: int = 0,
    content: str | None = None,
    observed_at: datetime = datetime(2026, 9, 12, tzinfo=UTC),
) -> CharacterMemory:
    """Build one detailed memory fixture."""
    return CharacterMemory(
        character_id=character,
        source_message_id=source,
        sequence=sequence,
        content=content or source,
        observed_at=observed_at,
    )


def _summary(
    source: str,
    *,
    character: str = "dorothy",
    content: str = "ユーザーは朝に作業する。",
    observed_at: datetime = datetime(2026, 9, 12, tzinfo=UTC),
) -> CharacterMemorySummary:
    """Build one selection summary fixture."""
    return CharacterMemorySummary(
        character_id=character,
        source_message_id=source,
        content=content,
        observed_at=observed_at,
    )


@pytest.mark.anyio
async def test_detailed_memory_is_scoped_and_written_as_markdown(
    tmp_path: Path,
) -> None:
    store = MarkdownCharacterMemoryStore(tmp_path)
    now = datetime(2026, 9, 12, 1, 0, tzinfo=UTC)
    memories = [
        _memory("source-1", observed_at=now - timedelta(minutes=2)),
        _memory("source-2", observed_at=now - timedelta(minutes=1)),
        _memory("source-3", character="eris", observed_at=now - timedelta(minutes=1)),
    ]

    assert is_ok(await store.save(memories))
    result = await store.get_relevant(
        character_id="dorothy",
        before=(now, "source-9"),
    )

    assert is_ok(result)
    assert [memory.source_message_id for memory in result.value] == [
        "source-1",
        "source-2",
    ]
    document = (tmp_path / "dorothy" / "memories" / "source-1-0.md").read_text(
        encoding="utf-8"
    )
    assert "memory_type: character_memory" in document
    assert "character_id: dorothy" in document
    assert "source-1" in document


@pytest.mark.anyio
async def test_detailed_memory_save_is_idempotent(tmp_path: Path) -> None:
    store = MarkdownCharacterMemoryStore(tmp_path)
    first = _memory("source-1", content="最初のノート")
    duplicate = _memory("source-1", content="再試行時の別ノート")

    assert is_ok(await store.save([first]))
    assert is_ok(await store.save([duplicate]))
    result = await store.get_relevant(character_id="dorothy")

    assert is_ok(result)
    assert len(result.value) == 1
    assert result.value[0].content == "最初のノート"


@pytest.mark.anyio
async def test_selection_summary_rejects_stale_updates_and_reads_all_characters(
    tmp_path: Path,
) -> None:
    store = MarkdownCharacterMemoryStore(tmp_path)
    now = datetime(2026, 9, 12, 1, 0, tzinfo=UTC)
    first = _summary("source-1", observed_at=now - timedelta(minutes=1))
    stale = _summary(
        "source-0",
        content="古い要約",
        observed_at=now - timedelta(minutes=2),
    )
    newer = _summary(
        "source-2",
        content="新しい要約",
        observed_at=now,
    )

    assert is_ok(await store.save_selection_summary(first))
    assert is_ok(await store.save_selection_summary(stale))
    assert is_ok(await store.save_selection_summary(newer))
    result = await store.get_selection_summaries(
        character_ids=("dorothy", "eris"),
        before=(now + timedelta(seconds=1), "source-9"),
    )

    assert is_ok(result)
    assert set(result.value) == {"dorothy"}
    assert result.value["dorothy"].content == "新しい要約"
    document = (tmp_path / "dorothy" / "selection-summary.md").read_text(
        encoding="utf-8"
    )
    assert "memory_type: character_selection_summary" in document
    assert "message_id: source-2" in document


@pytest.mark.anyio
async def test_malformed_markdown_returns_repository_error(tmp_path: Path) -> None:
    path = tmp_path / "dorothy" / "memories" / "broken.md"
    path.parent.mkdir(parents=True)
    path.write_text("not markdown frontmatter", encoding="utf-8")
    store = MarkdownCharacterMemoryStore(tmp_path)

    result = await store.get_relevant(character_id="dorothy")

    assert is_err(result)


@pytest.mark.anyio
async def test_memory_cursor_breaks_timestamp_ties_before_applying_the_limit(
    tmp_path: Path,
) -> None:
    """Only earlier notes and summaries may influence a response at the same timestamp."""
    store = MarkdownCharacterMemoryStore(tmp_path)
    timestamp = datetime(2026, 9, 12, tzinfo=UTC)
    assert is_ok(
        await store.save(
            [_memory("source-1"), _memory("source-2"), _memory("source-3")]
        )
    )
    assert is_ok(await store.save_selection_summary(_summary("source-3")))

    memories = await store.get_relevant(
        character_id="dorothy", before=(timestamp, "source-3"), limit=1
    )
    summaries = await store.get_selection_summaries(
        character_ids=("dorothy",), before=(timestamp, "source-3")
    )

    assert is_ok(memories)
    assert [memory.source_message_id for memory in memories.value] == ["source-2"]
    assert is_ok(summaries) and summaries.value == {}

"""Markdown and YAML-frontmatter storage for character-owned memory."""

import logging
import os
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import cast
from urllib.parse import quote

import yaml
from flow_res import Err, Ok, Result

from app.contracts.ports.character_memory_store import ICharacterMemoryStore
from app.domain.character_memory import CharacterMemory, CharacterMemorySummary
from app.domain.repositories import RepositoryError, RepositoryErrorType

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
DEFAULT_CHARACTER_MEMORY_ROOT = Path("memory/characters")
_MEMORY_TYPE = "character_memory"
_SUMMARY_TYPE = "character_selection_summary"
_MEMORY_DIRECTORY = "memories"
_SUMMARY_FILENAME = "selection-summary.md"
_SEPARATOR = "\n---\n"
_FILESYSTEM_LOCK = RLock()


def _repository_error(error: Exception) -> Err[RepositoryError]:
    """Convert filesystem and document errors to the application error type."""
    logger.exception("Character Markdown memory operation failed")
    return Err(
        RepositoryError(
            type=RepositoryErrorType.UNEXPECTED,
            message=str(error),
        )
    )


def _mapping(value: object, label: str) -> dict[str, object]:
    """Validate one YAML mapping and narrow it for callers."""
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be a YAML mapping.")
    return cast(dict[str, object], value)


def _required_string(value: object, label: str) -> str:
    """Read one required non-empty string from frontmatter."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string.")
    return value.strip()


def _timestamp(value: object, label: str) -> datetime:
    """Read an ISO timestamp and normalize it to UTC."""
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an ISO timestamp string.")
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{label} must be an ISO timestamp string.") from error
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware.")
    return timestamp.astimezone(UTC)


def _path_segment(value: str) -> str:
    """Encode an identifier so it can safely be used as one path segment."""
    encoded = quote(value.strip(), safe="-_.~")
    if encoded in {"", ".", ".."}:
        raise ValueError("Memory path identifier cannot be empty or relative.")
    return encoded


def _split_document(document: str) -> tuple[dict[str, object], str]:
    """Split one Markdown document into frontmatter and body."""
    if not document.startswith("---\n"):
        raise ValueError("Memory document must start with YAML frontmatter.")
    separator_index = document.find(_SEPARATOR, len("---\n"))
    if separator_index < 0:
        raise ValueError("Memory document has no closing frontmatter marker.")
    raw_frontmatter = document[len("---\n") : separator_index]
    try:
        loaded: object = yaml.safe_load(raw_frontmatter)
    except yaml.YAMLError as error:
        raise ValueError("Memory document frontmatter is invalid YAML.") from error
    metadata = _mapping(loaded if loaded is not None else {}, "Memory frontmatter")
    return metadata, document[separator_index + len(_SEPARATOR) :].strip()


def _render_document(metadata: dict[str, object], content: str) -> str:
    """Render a Markdown document with safe YAML serialization."""
    frontmatter = yaml.safe_dump(
        metadata,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    ).rstrip()
    return f"---\n{frontmatter}\n---\n{content.strip()}\n"


def _atomic_write(path: Path, document: str) -> None:
    """Replace one document atomically within its destination directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(document)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def _is_before(
    observed_at: datetime,
    source_message_id: str,
    before: tuple[datetime, str] | None,
) -> bool:
    """Return whether a memory is strictly older than a source cursor."""
    if before is None:
        return True
    before_at, before_message_id = before
    return observed_at < before_at or (
        observed_at == before_at and source_message_id < before_message_id
    )


class MarkdownCharacterMemoryStore(ICharacterMemoryStore):
    """Persist detailed notes and selection summaries as Markdown documents."""

    def __init__(self, root: Path = DEFAULT_CHARACTER_MEMORY_ROOT) -> None:
        """Create a store rooted at a character-memory directory."""
        self._root = root

    def _character_directory(self, character_id: str) -> Path:
        """Return the directory for one character without allowing traversal."""
        return self._root / _path_segment(character_id)

    def _memory_path(self, memory: CharacterMemory) -> Path:
        """Return the stable path for one detailed memory note."""
        filename = f"{_path_segment(memory.source_message_id)}-{memory.sequence}.md"
        return (
            self._character_directory(memory.character_id)
            / _MEMORY_DIRECTORY
            / filename
        )

    def _summary_path(self, character_id: str) -> Path:
        """Return the stable path for one character's working summary."""
        return self._character_directory(character_id) / _SUMMARY_FILENAME

    @staticmethod
    def _read_memory(path: Path, expected_character_id: str) -> CharacterMemory:
        """Read and validate one detailed memory document."""
        metadata, content = _split_document(path.read_text(encoding="utf-8"))
        if metadata.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"Unsupported memory schema in '{path}'.")
        if metadata.get("memory_type") != _MEMORY_TYPE:
            raise ValueError(f"Unexpected memory type in '{path}'.")
        sequence = metadata.get("sequence")
        if not isinstance(sequence, int) or isinstance(sequence, bool):
            raise ValueError(f"Memory sequence in '{path}' must be an integer.")
        memory = CharacterMemory(
            character_id=_required_string(metadata.get("character_id"), "character_id"),
            source_message_id=_required_string(
                metadata.get("source_message_id"), "source_message_id"
            ),
            sequence=sequence,
            content=content,
            observed_at=_timestamp(metadata.get("observed_at"), "observed_at"),
        )
        if memory.character_id != expected_character_id:
            raise ValueError(f"Memory ownership does not match '{path}'.")
        return memory

    @staticmethod
    def _read_summary(path: Path, expected_character_id: str) -> CharacterMemorySummary:
        """Read and validate one selection-summary document."""
        metadata, content = _split_document(path.read_text(encoding="utf-8"))
        if metadata.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"Unsupported memory schema in '{path}'.")
        if metadata.get("memory_type") != _SUMMARY_TYPE:
            raise ValueError(f"Unexpected memory type in '{path}'.")
        cursor = _mapping(metadata.get("source_cursor"), "source_cursor")
        summary = CharacterMemorySummary(
            character_id=_required_string(metadata.get("character_id"), "character_id"),
            source_message_id=_required_string(
                cursor.get("message_id"), "source_cursor.message_id"
            ),
            content=content,
            observed_at=_timestamp(
                cursor.get("occurred_at"), "source_cursor.occurred_at"
            ),
        )
        if summary.character_id != expected_character_id:
            raise ValueError(f"Summary ownership does not match '{path}'.")
        return summary

    @staticmethod
    def _memory_document(memory: CharacterMemory) -> str:
        """Build the document for one detailed memory note."""
        return _render_document(
            {
                "schema_version": SCHEMA_VERSION,
                "memory_type": _MEMORY_TYPE,
                "character_id": memory.character_id,
                "source_message_id": memory.source_message_id,
                "sequence": memory.sequence,
                "observed_at": memory.observed_at.isoformat(),
                "status": "working",
            },
            memory.content,
        )

    @staticmethod
    def _summary_document(summary: CharacterMemorySummary) -> str:
        """Build the document for one selection summary."""
        return _render_document(
            {
                "schema_version": SCHEMA_VERSION,
                "memory_type": _SUMMARY_TYPE,
                "character_id": summary.character_id,
                "source_cursor": {
                    "occurred_at": summary.observed_at.isoformat(),
                    "message_id": summary.source_message_id,
                },
                "updated_at": datetime.now(UTC).isoformat(),
                "status": "working",
            },
            summary.content,
        )

    async def get_relevant(
        self,
        *,
        character_id: str,
        limit: int = 20,
        before: tuple[datetime, str] | None = None,
    ) -> Result[list[CharacterMemory], RepositoryError]:
        """Read detailed notes owned by the selected character."""
        try:
            if limit <= 0:
                return Err(
                    RepositoryError(
                        type=RepositoryErrorType.UNEXPECTED,
                        message="Memory limit must be greater than zero.",
                    )
                )
            if before is not None and (
                before[0].tzinfo is None or before[0].utcoffset() is None
            ):
                raise ValueError("Memory cursor must be timezone-aware.")
            memory_directory = (
                self._character_directory(character_id) / _MEMORY_DIRECTORY
            )
            with _FILESYSTEM_LOCK:
                if not memory_directory.exists():
                    return Ok([])
                memories = [
                    self._read_memory(path, character_id)
                    for path in memory_directory.glob("*.md")
                    if path.is_file()
                ]
            relevant = [
                memory
                for memory in memories
                if _is_before(
                    memory.observed_at,
                    memory.source_message_id,
                    before,
                )
            ]
            relevant.sort(
                key=lambda memory: (
                    memory.observed_at,
                    memory.source_message_id,
                    memory.sequence,
                ),
                reverse=True,
            )
            return Ok(list(reversed(relevant[:limit])))
        except (OSError, TypeError, ValueError) as error:
            return _repository_error(error)

    async def save(
        self, memories: Sequence[CharacterMemory]
    ) -> Result[None, RepositoryError]:
        """Save detailed notes idempotently by source message and sequence."""
        try:
            with _FILESYSTEM_LOCK:
                for memory in memories:
                    path = self._memory_path(memory)
                    if path.exists():
                        self._read_memory(path, memory.character_id)
                        continue
                    _atomic_write(path, self._memory_document(memory))
            return Ok(None)
        except (OSError, TypeError, ValueError) as error:
            return _repository_error(error)

    async def get_selection_summaries(
        self,
        *,
        character_ids: Sequence[str],
        before: tuple[datetime, str] | None = None,
    ) -> Result[dict[str, CharacterMemorySummary], RepositoryError]:
        """Read current working summaries for the eligible characters."""
        try:
            if before is not None and (
                before[0].tzinfo is None or before[0].utcoffset() is None
            ):
                raise ValueError("Memory cursor must be timezone-aware.")
            summaries: dict[str, CharacterMemorySummary] = {}
            with _FILESYSTEM_LOCK:
                for character_id in dict.fromkeys(character_ids):
                    path = self._summary_path(character_id)
                    if not path.exists():
                        continue
                    summary = self._read_summary(path, character_id)
                    if _is_before(
                        summary.observed_at,
                        summary.source_message_id,
                        before,
                    ):
                        summaries[summary.character_id] = summary
            return Ok(summaries)
        except (OSError, TypeError, ValueError) as error:
            return _repository_error(error)

    async def save_selection_summary(
        self, summary: CharacterMemorySummary
    ) -> Result[None, RepositoryError]:
        """Atomically save a summary unless the file already contains newer data."""
        try:
            with _FILESYSTEM_LOCK:
                path = self._summary_path(summary.character_id)
                if path.exists():
                    existing = self._read_summary(path, summary.character_id)
                    if existing.cursor >= summary.cursor:
                        return Ok(None)
                _atomic_write(path, self._summary_document(summary))
            return Ok(None)
        except (OSError, TypeError, ValueError) as error:
            return _repository_error(error)


__all__ = [
    "DEFAULT_CHARACTER_MEMORY_ROOT",
    "MarkdownCharacterMemoryStore",
    "SCHEMA_VERSION",
]

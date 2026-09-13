"""Filesystem-backed user Profile and Timeline memory."""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import cast
from urllib.parse import quote

import yaml
from flow_res import Err, Ok, Result

from app.contracts.messages.user_memory import (
    UserMemoryContext,
    UserMemoryProfile,
    UserMemoryProfilePatch,
    UserMemorySource,
    UserMemoryTimelinePatch,
    UserTimelineEntry,
)
from app.contracts.ports.user_memory import IUserMemoryStore
from app.domain.repositories import RepositoryError, RepositoryErrorType

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
DEFAULT_USER_MEMORY_ROOT = Path("memory/users")
_PROFILE_TYPE = "user_profile"
_TIMELINE_TYPE = "user_timeline"
_SEPARATOR = "\n---\n"
_FILESYSTEM_LOCK = RLock()


def _repository_error(error: Exception) -> Err[RepositoryError]:
    """Convert a filesystem or document error into a repository error."""
    logger.exception("User Markdown memory operation failed")
    return Err(RepositoryError(type=RepositoryErrorType.UNEXPECTED, message=str(error)))


def _path_segment(value: str) -> str:
    """Encode one owner ID into a safe, deterministic path segment."""
    encoded = quote(value.strip(), safe="-_.~")
    if encoded in {"", ".", ".."}:
        raise ValueError("Memory owner ID cannot be empty or relative.")
    return encoded


def _mapping(value: object, label: str) -> dict[str, object]:
    """Narrow YAML mappings before reading their fields."""
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be a YAML mapping.")
    return cast(dict[str, object], value)


def _required_string(value: object, label: str) -> str:
    """Read one required, non-empty string from front matter."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string.")
    return value.strip()


def _timestamp(value: object, label: str) -> datetime:
    """Read and normalize one timezone-aware ISO timestamp."""
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an ISO timestamp string.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{label} must be an ISO timestamp string.") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware.")
    return parsed.astimezone(UTC)


def _string_list(value: object, label: str) -> tuple[str, ...]:
    """Read a list of non-empty strings from front matter."""
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be a string list.")
    return tuple(item.strip() for item in value if item.strip())


def _confidence(value: object, label: str) -> float:
    """Read one bounded confidence value from front matter."""
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError(f"{label} must be numeric.")
    confidence = float(value)
    if not 0 <= confidence <= 1:
        raise ValueError(f"{label} is out of range.")
    return confidence


def _split_document(document: str) -> tuple[dict[str, object], str]:
    """Split YAML front matter from a Markdown body."""
    if not document.startswith("---\n"):
        raise ValueError("Memory document must start with YAML front matter.")
    separator_index = document.find(_SEPARATOR, len("---\n"))
    if separator_index < 0:
        raise ValueError("Memory document has no closing front matter marker.")
    try:
        loaded: object = yaml.safe_load(document[len("---\n") : separator_index])
    except yaml.YAMLError as error:
        raise ValueError("Memory document front matter is invalid YAML.") from error
    return _mapping(
        loaded if loaded is not None else {}, "Memory front matter"
    ), document[separator_index + len(_SEPARATOR) :].strip()


def _render_document(metadata: dict[str, object], content: str) -> str:
    """Render a Markdown document with safe YAML serialization."""
    front_matter = yaml.safe_dump(
        metadata,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    ).rstrip()
    return f"---\n{front_matter}\n---\n{content.strip()}\n"


def _atomic_write(path: Path, document: str) -> None:
    """Replace a document atomically after flushing its temporary file."""
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
            temporary_path.unlink(missing_ok=True)


def _as_utc(value: datetime) -> datetime:
    """Normalize an aware timestamp to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Reference time must be timezone-aware.")
    return value.astimezone(UTC)


def _merge_unique(
    existing: Iterable[str], new_values: Iterable[str], *, limit: int = 200
) -> tuple[str, ...]:
    """Merge strings while preserving recency and bounding file growth."""
    values = list(dict.fromkeys((*existing, *new_values)))
    return tuple(values[-limit:])


class MarkdownUserMemoryStore(IUserMemoryStore):
    """Persist isolated user memory under one directory per canonical User."""

    def __init__(self, root: Path = DEFAULT_USER_MEMORY_ROOT) -> None:
        """Create a store rooted at the configured user-memory directory."""
        self._root = root

    def _user_directory(self, user_id: str) -> Path:
        """Return the filesystem directory owned by one canonical user."""
        return self._root / _path_segment(user_id)

    def _profile_path(self, user_id: str) -> Path:
        """Return the user's Profile path."""
        return self._user_directory(user_id) / "profile.md"

    def _timeline_directory(self, user_id: str) -> Path:
        """Return the user's Timeline directory."""
        return self._user_directory(user_id) / "timeline"

    @staticmethod
    def _read_profile(path: Path, expected_user_id: str) -> UserMemoryProfile:
        """Read and validate a user Profile document."""
        metadata, summary = _split_document(path.read_text(encoding="utf-8"))
        if metadata.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"Unsupported memory schema in '{path}'.")
        if metadata.get("memory_type") != _PROFILE_TYPE:
            raise ValueError(f"Unexpected memory type in '{path}'.")
        user_id = _required_string(metadata.get("user_id"), "user_id")
        if user_id != expected_user_id:
            raise ValueError(f"Profile ownership does not match '{path}'.")
        return UserMemoryProfile(
            user_id=user_id,
            summary=summary,
            traits=_string_list(metadata.get("traits", []), "traits"),
            preferences=_string_list(metadata.get("preferences", []), "preferences"),
            source_message_ids=_string_list(
                metadata.get("source_message_ids", []), "source_message_ids"
            ),
            updated_at=_timestamp(metadata.get("updated_at"), "updated_at"),
            confidence=_confidence(metadata.get("confidence", 0.0), "confidence"),
            created_at=_timestamp(
                metadata.get("created_at") or metadata.get("updated_at"),
                "created_at",
            ),
        )

    @staticmethod
    def _read_timeline(path: Path, expected_user_id: str) -> UserTimelineEntry:
        """Read and validate one Timeline document."""
        metadata, summary = _split_document(path.read_text(encoding="utf-8"))
        if metadata.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"Unsupported memory schema in '{path}'.")
        if metadata.get("memory_type") != _TIMELINE_TYPE:
            raise ValueError(f"Unexpected memory type in '{path}'.")
        user_id = _required_string(metadata.get("user_id"), "user_id")
        if user_id != expected_user_id:
            raise ValueError(f"Timeline ownership does not match '{path}'.")
        return UserTimelineEntry(
            id=_required_string(metadata.get("id"), "id"),
            user_id=user_id,
            day=_required_string(metadata.get("day"), "day"),
            title=_required_string(metadata.get("title"), "title"),
            summary=summary,
            source_message_ids=_string_list(
                metadata.get("source_message_ids", []), "source_message_ids"
            ),
            confidence=_confidence(
                metadata.get("confidence"), f"Timeline confidence in '{path}'"
            ),
            occurred_at=_timestamp(metadata.get("occurred_at"), "occurred_at"),
            updated_at=_timestamp(metadata.get("updated_at"), "updated_at"),
        )

    async def get_context(
        self, user_id: str, *, limit: int = 20
    ) -> Result[UserMemoryContext, RepositoryError]:
        """Read one user's Profile and most recent Timeline entries."""
        try:
            if limit <= 0:
                raise ValueError("User memory limit must be greater than zero.")
            profile_path = self._profile_path(user_id)
            timeline_directory = self._timeline_directory(user_id)
            with _FILESYSTEM_LOCK:
                profile = (
                    self._read_profile(profile_path, user_id)
                    if profile_path.exists()
                    else None
                )
                entries = (
                    [
                        self._read_timeline(path, user_id)
                        for path in timeline_directory.glob("*.md")
                        if path.is_file()
                    ]
                    if timeline_directory.exists()
                    else []
                )
            entries.sort(key=lambda entry: (entry.occurred_at, entry.id), reverse=True)
            return Ok(
                UserMemoryContext(profile=profile, timeline=tuple(entries[:limit]))
            )
        except (OSError, TypeError, ValueError) as error:
            return _repository_error(error)

    def _load_profile(self, user_id: str) -> UserMemoryProfile | None:
        """Load an existing Profile while holding the filesystem lock."""
        path = self._profile_path(user_id)
        return self._read_profile(path, user_id) if path.exists() else None

    @staticmethod
    def _profile_document(profile: UserMemoryProfile) -> str:
        """Render a Profile document."""
        return _render_document(
            {
                "schema_version": SCHEMA_VERSION,
                "memory_type": _PROFILE_TYPE,
                "user_id": profile.user_id,
                "traits": list(profile.traits),
                "preferences": list(profile.preferences),
                "source_message_ids": list(profile.source_message_ids),
                "confidence": profile.confidence,
                "created_at": (profile.created_at or profile.updated_at).isoformat(),
                "updated_at": profile.updated_at.isoformat(),
            },
            profile.summary,
        )

    @staticmethod
    def _timeline_id(user_id: str, day: str, source_ids: Iterable[str]) -> str:
        """Build a stable Timeline ID from server-owned evidence."""
        material = "\n".join((user_id, day, *sorted(set(source_ids))))
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _timeline_document(entry: UserTimelineEntry) -> str:
        """Render one Timeline document."""
        return _render_document(
            {
                "schema_version": SCHEMA_VERSION,
                "memory_type": _TIMELINE_TYPE,
                "id": entry.id,
                "user_id": entry.user_id,
                "day": entry.day,
                "title": entry.title,
                "source_message_ids": list(entry.source_message_ids),
                "confidence": entry.confidence,
                "occurred_at": entry.occurred_at.isoformat(),
                "updated_at": entry.updated_at.isoformat(),
            },
            entry.summary,
        )

    async def apply(
        self,
        *,
        user_id: str,
        profile_patch: UserMemoryProfilePatch | None,
        timeline_patches: tuple[UserMemoryTimelinePatch, ...],
        source_messages: tuple[UserMemorySource, ...],
        reference_time: datetime,
        day: str,
    ) -> Result[None, RepositoryError]:
        """Apply only patches whose evidence belongs to the requested User."""
        try:
            reference_time = _as_utc(reference_time)
            owner = _required_string(user_id, "user_id")
            source_by_id = {source.message_id: source for source in source_messages}
            if len(source_by_id) != len(source_messages):
                raise ValueError("Memory source IDs must be unique.")
            if any(source.user_id != owner for source in source_messages):
                raise ValueError("Memory source ownership does not match user_id.")
            if profile_patch is not None and profile_patch.update_mode != "defer":
                if not set(profile_patch.source_message_ids) <= source_by_id.keys():
                    raise ValueError("Profile patch cites an unknown source.")
            for patch in timeline_patches:
                if not set(patch.source_message_ids) <= source_by_id.keys():
                    raise ValueError("Timeline patch cites an unknown source.")
            with _FILESYSTEM_LOCK:
                existing = self._load_profile(owner)
                if profile_patch is not None and profile_patch.update_mode != "defer":
                    if existing is None:
                        existing = UserMemoryProfile(
                            user_id=owner,
                            summary="",
                            traits=(),
                            preferences=(),
                            source_message_ids=(),
                            updated_at=reference_time,
                            created_at=reference_time,
                        )
                    if profile_patch.update_mode == "replace":
                        summary = (profile_patch.summary or "").strip()
                        traits = tuple(dict.fromkeys(profile_patch.traits))
                        preferences = tuple(dict.fromkeys(profile_patch.preferences))
                    else:
                        summary = (
                            profile_patch.summary.strip()
                            if profile_patch.summary is not None
                            else existing.summary
                        )
                        traits = _merge_unique(existing.traits, profile_patch.traits)
                        preferences = _merge_unique(
                            existing.preferences, profile_patch.preferences
                        )
                    profile = UserMemoryProfile(
                        user_id=owner,
                        summary=summary,
                        traits=traits,
                        preferences=preferences,
                        source_message_ids=_merge_unique(
                            existing.source_message_ids,
                            profile_patch.source_message_ids,
                        ),
                        updated_at=reference_time,
                        confidence=profile_patch.confidence,
                        created_at=existing.created_at or existing.updated_at,
                    )
                    _atomic_write(
                        self._profile_path(owner),
                        self._profile_document(profile),
                    )

                source_by_id = {source.message_id: source for source in source_messages}
                for patch in timeline_patches:
                    observed_at = max(
                        source_by_id[source_id].occurred_at
                        for source_id in patch.source_message_ids
                    ).astimezone(UTC)
                    entry = UserTimelineEntry(
                        id=self._timeline_id(owner, day, patch.source_message_ids),
                        user_id=owner,
                        day=day,
                        title=patch.title.strip(),
                        summary=patch.summary.strip(),
                        source_message_ids=tuple(
                            dict.fromkeys(patch.source_message_ids)
                        ),
                        confidence=patch.confidence,
                        occurred_at=observed_at,
                        updated_at=reference_time,
                    )
                    _atomic_write(
                        self._timeline_directory(owner) / f"{entry.id}.md",
                        self._timeline_document(entry),
                    )
            return Ok(None)
        except (OSError, TypeError, ValueError) as error:
            return _repository_error(error)


__all__ = ["DEFAULT_USER_MEMORY_ROOT", "MarkdownUserMemoryStore"]

"""Character-owned memories shared across the configured Discord server."""

from dataclasses import dataclass
from datetime import UTC, datetime

MAX_CHARACTER_MEMORY_LENGTH = 500
MAX_CHARACTER_MEMORY_SUMMARY_LENGTH = 400


@dataclass(frozen=True, slots=True)
class CharacterMemory:
    """One durable note owned by one character."""

    character_id: str
    source_message_id: str
    sequence: int
    content: str
    observed_at: datetime

    def __post_init__(self) -> None:
        """Validate ownership, provenance and the memory timestamp."""
        for value, label in (
            (self.character_id, "Character ID"),
            (self.source_message_id, "Source message ID"),
        ):
            normalized = value.strip()
            if not normalized:
                raise ValueError(f"{label} cannot be empty.")
            object.__setattr__(self, label.lower().replace(" ", "_"), normalized)

        content = self.content.strip()
        if not content:
            raise ValueError("Character memory content cannot be empty.")
        if len(content) > MAX_CHARACTER_MEMORY_LENGTH:
            raise ValueError("Character memory content exceeds the maximum length.")
        object.__setattr__(self, "content", content)

        if self.sequence < 0:
            raise ValueError("Character memory sequence cannot be negative.")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("Character memory timestamp must be timezone-aware.")
        object.__setattr__(
            self,
            "observed_at",
            self.observed_at.astimezone(UTC),
        )


@dataclass(frozen=True, slots=True)
class CharacterMemorySummary:
    """Compact working memory used when selecting a character."""

    character_id: str
    source_message_id: str
    content: str
    observed_at: datetime

    def __post_init__(self) -> None:
        """Validate ownership, provenance and the summary timestamp."""
        for value, label in (
            (self.character_id, "Character ID"),
            (self.source_message_id, "Source message ID"),
        ):
            normalized = value.strip()
            if not normalized:
                raise ValueError(f"{label} cannot be empty.")
            object.__setattr__(
                self,
                label.lower().replace(" ", "_"),
                normalized,
            )

        content = self.content.strip()
        if not content:
            raise ValueError("Character memory summary cannot be empty.")
        if len(content) > MAX_CHARACTER_MEMORY_SUMMARY_LENGTH:
            raise ValueError("Character memory summary exceeds the maximum length.")
        object.__setattr__(self, "content", content)

        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError(
                "Character memory summary timestamp must be timezone-aware."
            )
        object.__setattr__(self, "observed_at", self.observed_at.astimezone(UTC))

    @property
    def cursor(self) -> tuple[datetime, str]:
        """Return the source cursor used to reject stale updates."""
        return self.observed_at, self.source_message_id

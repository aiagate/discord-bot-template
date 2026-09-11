"""Messages and data models for Discord Times episodes."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class TimesPost:
    """One Times post with private memory updates for its speaker."""

    character_name: str
    content: str
    memory_candidates: tuple[str, ...] = ()
    selection_summary: str | None = None


@dataclass(frozen=True, slots=True)
class TimesEpisodePlan:
    """Durable episode plan with its source conversation and explicit delivery channel."""

    source_message_id: str
    guild_id: str
    channel_id: str
    delivery_channel_id: str
    posts: tuple[TimesPost, ...] = ()
    status: str = "PENDING"
    next_post_index: int = 0
    next_chunk_index: int | None = None  # Older plans tracked only whole posts.
    last_message_id: str | None = None
    failure: str | None = None
    created_at: datetime | None = None
    attempt_started_at: datetime | None = None

    @property
    def complete(self) -> bool:
        """Return whether all posts have been delivered or marked completed."""
        return self.status == "COMPLETED" or (
            bool(self.posts) and self.next_post_index >= len(self.posts)
        )

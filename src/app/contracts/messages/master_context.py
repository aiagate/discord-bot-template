"""Private master context shared with character conversations."""

from dataclasses import dataclass

MAX_MASTER_CONTEXT_LENGTH = 8_000


@dataclass(frozen=True, slots=True)
class DiscordMaster:
    """Fixed Discord identity and private personalization context."""

    user_id: str | None = None
    context: str | None = None

    def __post_init__(self) -> None:
        """Validate the identity and normalize the private context."""
        if self.user_id is not None:
            user_id = self.user_id.strip()
            if (
                not user_id.isascii()
                or not user_id.isdecimal()
                or len(user_id) > 20
                or user_id.startswith("0")
                or not 0 < int(user_id) < 2**64
            ):
                raise ValueError("Master user ID must be a positive Discord snowflake.")
            object.__setattr__(self, "user_id", user_id)

        if self.context is not None:
            context = self.context.strip()
            if not context:
                raise ValueError("Master context cannot be empty.")
            if len(context) > MAX_MASTER_CONTEXT_LENGTH:
                raise ValueError(
                    "Master context exceeds the maximum length "
                    f"({MAX_MASTER_CONTEXT_LENGTH} characters)."
                )
            object.__setattr__(self, "context", context)

    def to_prompt(self) -> dict[str, str] | None:
        """Return the configured identity and context for a model prompt."""
        if self.user_id is None and self.context is None:
            return None
        prompt: dict[str, str] = {}
        if self.user_id is not None:
            prompt.update({"user_id": self.user_id, "mention": f"<@{self.user_id}>"})
        if self.context is not None:
            prompt["context"] = self.context
        return prompt


UNCONFIGURED_MASTER = DiscordMaster()

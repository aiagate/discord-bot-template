"""Load the collective's explicit operating scope without copying credentials."""

from pathlib import Path
from typing import Self

from pydantic import Field, model_validator

from app.contracts.messages.collective import Character, CollectiveSettings, Record
from app.domain.characters import AI_MAID_CHARACTERS, AI_MAID_COMMON_STYLE


class BotCollectiveConfig(Record):
    """One guild, one master, distinct channels, and secret environment names."""

    root: Path
    guild_id: int = Field(gt=0)
    master_id: int = Field(gt=0)
    master_channel_id: int = Field(gt=0)
    times_channel_id: int = Field(gt=0)
    master_webhook_env: str = "MAID_MASTER_WEBHOOK_URL"
    times_webhook_env: str = "MAID_TIMES_WEBHOOK_URL"
    gemini_key_env: str = "GEMINI_API_KEY"
    gemini_model: str = "gemini-3.8-flash"
    codex_model: str | None = None
    max_output_tokens: int = Field(default=8192, gt=0)
    token_margin: int = Field(default=16384, ge=0)
    agy_skill: Path
    settings: CollectiveSettings = Field(default_factory=CollectiveSettings)

    @model_validator(mode="after")
    def distinct_channels(self) -> Self:
        """Prevent private discussion and master reports sharing a destination."""
        if self.master_channel_id == self.times_channel_id:
            raise ValueError("Master and Times channels must be distinct")
        return self


def initialize_characters(root: Path) -> None:
    """Create missing portable profiles from the established maid definitions."""
    for definition in AI_MAID_CHARACTERS:
        path = root / "characters" / f"{definition.character_id}.json"
        if path.exists():
            continue
        character = Character(
            id=definition.character_id,
            name=definition.display_name,
            persona="\n".join(
                (*AI_MAID_COMMON_STYLE, definition.persona, definition.speech_style)
            ),
            public_profile=f"{definition.name}: {definition.position}。"
            + "、".join(definition.responsibilities),
            avatar_url=definition.avatar_url,
            work_guidance=definition.work_guidance,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(character.model_dump_json(indent=2))


def load_characters(root: Path) -> dict[str, Character]:
    """Validate configured identity files before any model execution."""
    characters: dict[str, Character] = {}
    for path in sorted((root / "characters").glob("*.json")):
        character = Character.model_validate_json(path.read_text())
        if character.id != path.stem or character.id in characters:
            raise ValueError("Character filenames and unique IDs must match")
        characters[character.id] = character
    if not characters:
        raise ValueError("No character profiles; initialize the collective first")
    return characters

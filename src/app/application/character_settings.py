"""Build the runtime roster from the canonical character definitions."""

from dataclasses import replace
from urllib.parse import quote

from app.domain.characters import (
    AI_MAID_CHARACTERS,
    AI_MAID_COMMON_STYLE,
    CharacterRoster,
)


def load_ai_maid_definitions() -> CharacterRoster:
    """Load canonical AI maid definitions with runtime avatar URLs."""
    characters = tuple(
        replace(
            character,
            avatar_url=(
                "https://api.dicebear.com/10.x/identicon/png"
                f"?seed={quote(character.name, safe='')}&size=128"
            ),
        )
        for character in AI_MAID_CHARACTERS
    )
    return CharacterRoster(AI_MAID_COMMON_STYLE, characters)

"""Tests for the runtime roster builder."""

from app.application.character_settings import load_ai_maid_definitions
from app.domain.characters import AI_MAID_CHARACTERS, AI_MAID_COMMON_STYLE


def test_runtime_roster_uses_canonical_profiles_and_runtime_avatars() -> None:
    """Runtime decoration leaves the canonical character profiles unchanged."""
    roster = load_ai_maid_definitions()

    assert roster.common_style == AI_MAID_COMMON_STYLE
    assert len(roster.characters) == len(AI_MAID_CHARACTERS)
    for runtime, canonical in zip(roster.characters, AI_MAID_CHARACTERS, strict=True):
        assert runtime.name == canonical.name
        assert runtime.character_id == canonical.character_id
        assert runtime.position == canonical.position
        assert runtime.responsibilities == canonical.responsibilities
        assert runtime.persona == canonical.persona
        assert runtime.speech_style == canonical.speech_style
        assert runtime.work_guidance == canonical.work_guidance
        assert runtime.avatar_url is not None

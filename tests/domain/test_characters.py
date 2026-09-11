"""Tests for the canonical AI maid character definitions."""

from app.domain.characters import AI_MAID_CHARACTERS, AI_MAID_COMMON_STYLE


def test_ai_maid_roster_has_one_canonical_position_per_character() -> None:
    """The roster keeps names and display positions stable."""
    assert [
        (character.name, character.position) for character in AI_MAID_CHARACTERS
    ] == [
        ("Dorothy", "メイド長"),
        ("Eris", "辛辣担当"),
        ("Yui", "記録担当"),
        ("Astra", "設計担当"),
        ("Noa", "開発環境担当"),
        ("Mira", "AI研究担当"),
        ("Lilia", "研究担当"),
        ("Sophia", "計算資源担当"),
        ("Rin", "工作担当"),
        ("Celeste", "生活担当"),
    ]
    assert len({character.name for character in AI_MAID_CHARACTERS}) == len(
        AI_MAID_CHARACTERS
    )


def test_each_character_has_scope_and_voice_guidance() -> None:
    """Each character definition contains enough guidance to avoid role drift."""
    assert all(character.responsibilities for character in AI_MAID_CHARACTERS)
    assert all(character.persona for character in AI_MAID_CHARACTERS)
    assert all(character.speech_style for character in AI_MAID_CHARACTERS)


def test_common_style_preserves_the_board_rules() -> None:
    """Shared board behavior is defined once for every character."""
    assert "マスター" in AI_MAID_COMMON_STYLE[0]
    assert "忖度せず" in AI_MAID_COMMON_STYLE[1]
    assert "メイド同士" in AI_MAID_COMMON_STYLE[2]
    assert "事実" in AI_MAID_COMMON_STYLE[3]


def test_domain_definitions_do_not_depend_on_avatar_services() -> None:
    """Avatar URLs are assigned by application settings."""
    assert all(character.avatar_url is None for character in AI_MAID_CHARACTERS)

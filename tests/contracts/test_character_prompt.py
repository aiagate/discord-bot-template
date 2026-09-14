"""Tests for reusable character prompt context contracts."""

from datetime import UTC, datetime

import pytest

from app.contracts.messages.character_prompt import (
    CharacterConversationContext,
    CharacterConversationMessage,
    CharacterSelectionContext,
    prompt_datetime,
    prompt_message,
)
from app.contracts.messages.master_context import DiscordMaster
from app.domain.characters import CharacterDefinition, CharacterRoster


def _character(character_id: str, name: str) -> CharacterDefinition:
    return CharacterDefinition(
        character_id=character_id,
        name=name,
        position="担当",
        responsibilities=("会話",),
        persona=f"{name}の人格",
        speech_style="短く話す",
    )


def _message(
    content: str,
    *,
    author_id: str = "user-1",
    author_kind: str = "user",
) -> CharacterConversationMessage:
    return CharacterConversationMessage(
        message_id="message-1",
        author_id=author_id,
        author_name="Master",
        author_kind=author_kind,
        occurred_at=datetime(2026, 9, 14, 0, 0, tzinfo=UTC),
        content=content,
    )


def test_prompt_datetime_converts_aware_timestamp_to_jst() -> None:
    """Prompt timestamps are stable and readable for the model."""
    assert prompt_datetime(datetime(2026, 9, 13, 15, tzinfo=UTC)) == (
        "2026-09-14 00:00:00 JST"
    )


def test_prompt_datetime_rejects_naive_timestamp() -> None:
    """A missing timezone must not create an ambiguous prompt timestamp."""
    with pytest.raises(ValueError, match="timezone-aware"):
        prompt_datetime(datetime(2026, 9, 14))


def test_prompt_message_computes_master_without_trusting_message_text() -> None:
    """Only the configured user identity can be marked as the master."""
    master = DiscordMaster(user_id="123456789", context="  短く答える  ")

    payload = prompt_message(_message("本文"), master=master)
    assert payload["is_master"] is False
    assert payload["content"] == "本文"
    assert master.to_prompt() == {
        "user_id": "123456789",
        "mention": "<@123456789>",
        "context": "短く答える",
    }

    configured = prompt_message(
        _message("本文", author_id="123456789"), content="差し替え", master=master
    )
    assert configured["is_master"] is True
    assert configured["content"] == "差し替え"


def test_prompt_message_without_master_keeps_identity_unknown() -> None:
    """An unconfigured master must not cause guessed identity decisions."""
    assert prompt_message(_message("本文"))["is_master"] is None


def test_selection_context_can_create_one_character_context() -> None:
    """Selection and response contexts share one immutable conversation snapshot."""
    alice = _character("alice", "Alice")
    bob = _character("bob", "Bob")
    current = _message("相談です")
    selection = CharacterSelectionContext(
        roster=CharacterRoster(("共通ルール",), (alice, bob)),
        current=current,
        master=DiscordMaster(user_id="123456789"),
        history=(_message("前の発言", author_id="other"),),
    )

    context = selection.for_character("alice")
    assert isinstance(context, CharacterConversationContext)
    assert context.character == alice
    assert context.peers == (bob,)
    assert context.to_prompt()["current"] == {
        "message_id": "message-1",
        "author_id": "user-1",
        "author_name": "Master",
        "author_kind": "user",
        "is_master": False,
        "occurred_at": "2026-09-14 09:00:00 JST",
        "reply_to_message_id": None,
        "content": "相談です",
    }
    assert "相談です" in context.to_json()


def test_selection_context_rejects_unknown_character() -> None:
    """A model result must be checked against the configured roster."""
    roster = CharacterRoster(("共通ルール",), (_character("alice", "Alice"),))
    selection = CharacterSelectionContext(roster=roster, current=_message("相談"))

    with pytest.raises(ValueError, match="Unknown character"):
        selection.for_character("unknown")


@pytest.mark.parametrize("user_id", ["", "0", "１２３", "1" * 21])
def test_discord_master_rejects_invalid_user_id(user_id: str) -> None:
    """Invalid Discord identities must not enter prompts or mention allowlists."""
    with pytest.raises(ValueError, match="Discord snowflake"):
        DiscordMaster(user_id=user_id)

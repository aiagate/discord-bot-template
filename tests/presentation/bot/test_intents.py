"""Tests for the minimal Discord gateway intents used by the bot."""

import discord

from app.presentation.bot import __main__ as bot_main
from app.presentation.bot.intents import create_bot_intents


def test_enabled_intents_are_exactly_the_minimum_required() -> None:
    """Only the intents required by current capabilities are enabled."""
    intents = create_bot_intents()

    expected = discord.Intents(
        guilds=True,
        guild_messages=True,
        dm_messages=True,
        message_content=True,
    )

    assert intents.value == expected.value


def test_message_content_is_the_only_privileged_intent_enabled() -> None:
    """Message Content is required; every other privileged intent stays off."""
    intents = create_bot_intents()

    assert intents.message_content is True
    assert intents.members is False
    assert intents.presences is False
    assert intents.auto_moderation_configuration is False
    assert intents.auto_moderation_execution is False


def test_unrelated_event_intents_are_disabled() -> None:
    """Current Cogs do not use typing, voice, reactions, bans or invites."""
    intents = create_bot_intents()

    assert intents.typing is False
    assert intents.dm_typing is False
    assert intents.guild_typing is False
    assert intents.voice_states is False
    assert intents.reactions is False
    assert intents.bans is False
    assert intents.invites is False
    assert intents.integrations is False
    assert intents.webhooks is False


def test_bot_uses_the_minimal_intents() -> None:
    """MyBot is constructed with the shared minimal intent set."""
    bot = bot_main.MyBot()

    assert bot.intents.value == create_bot_intents().value

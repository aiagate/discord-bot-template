"""Tests for runtime AI maid character settings."""

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from app.application.character_settings import (
    load_ai_maid_definitions,
    load_character_settings,
)


def test_local_override_replaces_only_specified_fields(tmp_path: Path) -> None:
    """A local override preserves defaults for omitted fields."""
    override_path = tmp_path / "characters.override.json"
    defaults = load_ai_maid_definitions()
    override_path.write_text(
        json.dumps(
            {
                "common_style": ["ローカル環境では簡潔に話す。"],
                "characters": {
                    "Eris": {
                        "position": "毒舌担当",
                        "speech_style": "短く、さらに鋭く話す。",
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    roster = load_ai_maid_definitions(override_path)
    common_style, characters = roster.common_style, roster.characters
    by_name = {character.name: character for character in characters}

    assert common_style == ("ローカル環境では簡潔に話す。",)
    assert by_name["Eris"].position == "毒舌担当"
    assert by_name["Eris"].speech_style == "短く、さらに鋭く話す。"
    assert by_name["Eris"].persona == next(
        character.persona
        for character in defaults.characters
        if character.name == "Eris"
    )
    assert by_name["Dorothy"].position == "メイド長"


def test_local_override_rejects_unknown_character(tmp_path: Path) -> None:
    """A typo in a character name fails instead of being silently ignored."""
    override_path = tmp_path / "characters.override.json"
    override_path.write_text(
        json.dumps({"characters": {"Doroty": {"position": "別名"}}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown names"):
        load_ai_maid_definitions(override_path)


def test_local_override_supports_avatar_url(tmp_path: Path) -> None:
    """A local override can set avatar_url for a character."""
    override_path = tmp_path / "characters.override.json"
    override_path.write_text(
        json.dumps(
            {
                "characters": {
                    "Dorothy": {
                        "avatar_url": "https://example.com/dorothy.png",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    characters = load_ai_maid_definitions(override_path).characters
    by_name = {character.name: character for character in characters}

    assert by_name["Dorothy"].avatar_url == "https://example.com/dorothy.png"
    assert by_name["Eris"].avatar_url == (
        "https://api.dicebear.com/10.x/identicon/png?seed=Eris&size=128"
    )


def test_local_override_rejects_invalid_avatar_url_type(tmp_path: Path) -> None:
    """A non-string avatar_url value raises ValueError."""
    override_path = tmp_path / "characters.override.json"
    override_path.write_text(
        json.dumps(
            {
                "characters": {
                    "Dorothy": {
                        "avatar_url": 12345,
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must be a string or null"):
        load_ai_maid_definitions(override_path)


def test_default_definitions_ignore_working_directory_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "characters.override.json").write_text("{invalid", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert len(load_ai_maid_definitions().characters) == 10


def test_explicit_missing_override_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        load_ai_maid_definitions(tmp_path / "missing.json")


@pytest.mark.parametrize(
    "url", ["file:///tmp/avatar.png", "https://", "javascript:alert(1)"]
)
def test_avatar_requires_an_http_url(tmp_path: Path, url: str) -> None:
    path = tmp_path / "override.json"
    path.write_text(
        json.dumps({"characters": {"Dorothy": {"avatar_url": url}}}), encoding="utf-8"
    )
    with pytest.raises(ValueError):
        load_ai_maid_definitions(path)


def test_mcp_settings_stay_out_of_public_profiles(tmp_path: Path) -> None:
    path = tmp_path / "characters.json"
    path.write_text(
        json.dumps(
            {
                "characters": {
                    "Dorothy": {
                        "mcp_servers": {
                            "notes": {
                                "command": "uvx",
                                "args": ["notes-server"],
                                "env_vars": {"TOKEN": "NOTES_TOKEN"},
                                "allowed_tools": ["read_note"],
                            },
                            "calendar": {
                                "url": "https://calendar.example/mcp",
                                "headers_env": {"Authorization": "CALENDAR_AUTH"},
                                "allowed_tools": ["list_events"],
                            },
                        }
                    },
                    "Eris": {"mcp_servers": {}},
                }
            }
        ),
        encoding="utf-8",
    )
    settings = load_character_settings(path)
    assert settings.roster == load_ai_maid_definitions()
    assert set(settings.mcp_servers) == {"Dorothy"}
    notes, calendar = settings.mcp_servers["Dorothy"]
    assert notes.command == "uvx" and notes.args == ("notes-server",)
    assert notes.env_vars == (("TOKEN", "NOTES_TOKEN"),)
    assert notes.allowed_tools == ("read_note",)
    assert calendar.headers_env == (("Authorization", "CALENDAR_AUTH"),)
    assert calendar.url == "https://calendar.example/mcp"
    assert "MCP" not in json.dumps(asdict(settings.roster))
    assert "NOTES_TOKEN" not in json.dumps(asdict(settings.roster))
    assert load_character_settings().mcp_servers == {}


@pytest.mark.parametrize(
    "server",
    [
        None,
        [],
        {},
        {"url": "https://example.com/mcp"},
        {"url": "https://example.com/mcp", "allowed_tools": []},
        {"url": "https://example.com/mcp", "allowed_tools": ["*"]},
        {"url": "https://example.com/mcp", "allowed_tools": ["read", "read"]},
        {"url": "https://example.com/mcp", "allowed_tools": [1]},
        {
            "url": "https://example.com/mcp",
            "command": "server",
            "allowed_tools": ["read"],
        },
        {"url": "file:///tmp/socket", "allowed_tools": ["read"]},
        {"url": "https://", "allowed_tools": ["read"]},
        {"url": "https://secret@example.com/mcp", "allowed_tools": ["read"]},
        {"url": "https://example.com/mcp#fragment", "allowed_tools": ["read"]},
        {
            "url": "https://example.com/mcp",
            "allowed_tools": ["read"],
            "headers_env": {"Authorization": "Bearer secret"},
        },
        {"url": "https://example.com/mcp", "allowed_tools": ["read"], "env_vars": {}},
        {"command": "", "allowed_tools": ["read"]},
        {"command": "server", "args": "argument", "allowed_tools": ["read"]},
        {"command": "server", "allowed_tools": ["read"], "headers_env": {}},
        {"command": "server", "allowed_tools": ["read"], "env_vars": {"": "TOKEN"}},
        {"command": "server", "allowed_tools": ["read"], "typo": True},
    ],
)
def test_invalid_mcp_settings_are_rejected(tmp_path: Path, server: object) -> None:
    path = tmp_path / "characters.json"
    path.write_text(
        json.dumps({"characters": {"Dorothy": {"mcp_servers": {"test": server}}}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_character_settings(path)

"""Runtime character settings with optional local overrides."""

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast
from urllib.parse import quote, urlsplit

from app.contracts.messages.character_mcp import CharacterMcpServer
from app.domain.characters import (
    AI_MAID_CHARACTERS as DEFAULT_AI_MAID_CHARACTERS,
)
from app.domain.characters import (
    AI_MAID_COMMON_STYLE as DEFAULT_AI_MAID_COMMON_STYLE,
)
from app.domain.characters import (
    CharacterDefinition,
    CharacterRoster,
)

_OVERRIDE_FIELDS = frozenset(
    {
        "position",
        "responsibilities",
        "persona",
        "speech_style",
        "avatar_url",
        "mcp_servers",
    }
)


@dataclass(frozen=True, slots=True)
class CharacterSettings:
    """Keep public identities separate from private tool configuration."""

    roster: CharacterRoster
    mcp_servers: dict[str, tuple[CharacterMcpServer, ...]]


def _as_object(value: object, label: str) -> dict[str, object]:
    """Validate and return a JSON object."""
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be a JSON object.")
    return cast(dict[str, object], value)


def _as_strings(value: object, label: str) -> tuple[str, ...]:
    """Validate and normalize a non-empty JSON string array."""
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) for item in value)
    ):
        raise ValueError(f"{label} must be a non-empty string array.")

    values = tuple(item.strip() for item in cast(list[str], value))
    if any(not item for item in values):
        raise ValueError(f"{label} must not contain empty strings.")
    return values


def _as_string(value: object, label: str) -> str:
    """Validate and normalize one non-empty JSON string."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string.")
    return value.strip()


def _reject_unknown_keys(
    values: dict[str, object],
    allowed: frozenset[str],
    label: str,
) -> None:
    """Reject misspelled or unsupported override keys."""
    unknown = set(values) - allowed
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ValueError(f"{label} contains unknown keys: {names}.")


def _override_string(
    values: dict[str, object],
    field: str,
    default: str,
    label: str,
) -> str:
    """Return one overridden string or its default value."""
    if field not in values:
        return default
    return _as_string(values[field], f"{label}.{field}")


def _override_optional_string(
    values: dict[str, object],
    field: str,
    default: str | None,
    label: str,
) -> str | None:
    """Return one overridden optional string or its default value."""
    if field not in values:
        return default
    raw = values[field]
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError(f"{label}.{field} must be a string or null.")
    cleaned = raw.strip()
    if cleaned and (
        urlsplit(cleaned).scheme not in {"https", "http"}
        or not urlsplit(cleaned).netloc
    ):
        raise ValueError(f"{label}.{field} must be an HTTP(S) URL or null.")
    return cleaned if cleaned else None


def _override_strings(
    values: dict[str, object],
    field: str,
    default: tuple[str, ...],
    label: str,
) -> tuple[str, ...]:
    """Return overridden strings or their default values."""
    if field not in values:
        return default
    return _as_strings(values[field], f"{label}.{field}")


def _merge_character(
    character: CharacterDefinition,
    override: object,
) -> CharacterDefinition:
    """Apply a partial override to one default character."""
    values = _as_object(override, f"characters.{character.name}")
    label = f"characters.{character.name}"
    _reject_unknown_keys(values, _OVERRIDE_FIELDS, label)
    return CharacterDefinition(
        name=character.name,
        character_id=character.character_id,
        position=_override_string(values, "position", character.position, label),
        responsibilities=_override_strings(
            values,
            "responsibilities",
            character.responsibilities,
            label,
        ),
        persona=_override_string(values, "persona", character.persona, label),
        speech_style=_override_string(
            values,
            "speech_style",
            character.speech_style,
            label,
        ),
        avatar_url=_override_optional_string(
            values,
            "avatar_url",
            character.avatar_url,
            label,
        ),
    )


def _read_override(path: Path) -> dict[str, object]:
    """Read and validate the root object from an override file."""
    try:
        with path.open(encoding="utf-8") as file:
            value: object = json.load(file)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read character override file '{path}'.") from error

    values = _as_object(value, "Character override")
    _reject_unknown_keys(values, frozenset({"common_style", "characters"}), "Override")
    return values


def _environment_references(
    value: object, label: str, *, headers: bool = False
) -> tuple[tuple[str, str], ...]:
    values = _as_object(value, label)
    references: list[tuple[str, str]] = []
    for key, raw in values.items():
        valid_key = (
            re.fullmatch(r"[-!#$%&'*+.^_`|~0-9A-Za-z]+", key) is not None
            if headers
            else key.isascii() and key.isidentifier()
        )
        if not valid_key:
            raise ValueError(f"{label} contains an invalid name.")
        name = _as_string(raw, label)
        if not name.isascii() or not name.isidentifier():
            raise ValueError(f"{label} must reference environment variable names.")
        references.append((key, name))
    return tuple(references)


def _command_args(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(arg, str) and "\x00" not in arg for arg in value
    ):
        raise ValueError(f"{label} must be a string array without null characters.")
    return tuple(cast(list[str], value))


def _mcp_servers(value: object, label: str) -> tuple[CharacterMcpServer, ...]:
    servers: list[CharacterMcpServer] = []
    for name, raw in _as_object(value, label).items():
        _as_string(name, label)
        values = _as_object(raw, f"{label}.{name}")
        if ("url" in values) == ("command" in values):
            raise ValueError(f"{label}.{name} requires exactly one of url or command.")
        http = "url" in values
        _reject_unknown_keys(
            values,
            frozenset({"url", "headers_env", "allowed_tools"})
            if http
            else frozenset({"command", "args", "env_vars", "allowed_tools"}),
            f"{label}.{name}",
        )
        allowed = _as_strings(
            values.get("allowed_tools"), f"{label}.{name}.allowed_tools"
        )
        if len(set(allowed)) != len(allowed) or "*" in allowed:
            raise ValueError(
                f"{label}.{name}.allowed_tools must list unique tool names."
            )
        url = _as_string(values["url"], f"{label}.{name}.url") if http else None
        if url is not None:
            parsed = urlsplit(url)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.fragment
                or any(char.isspace() for char in url)
            ):
                raise ValueError(
                    f"{label}.{name}.url must be an HTTP(S) URL without credentials or fragments."
                )
        servers.append(
            CharacterMcpServer(
                name=name,
                allowed_tools=allowed,
                url=url,
                command=None
                if http
                else _as_string(values["command"], f"{label}.{name}.command"),
                args=_command_args(values.get("args", []), f"{label}.{name}.args"),
                env_vars=_environment_references(
                    values.get("env_vars", {}), f"{label}.{name}.env_vars"
                ),
                headers_env=_environment_references(
                    values.get("headers_env", {}),
                    f"{label}.{name}.headers_env",
                    headers=True,
                ),
            )
        )
    return tuple(servers)


def load_character_settings(
    override_path: Path | None = None,
) -> CharacterSettings:
    """Load public character profiles and their private MCP settings."""
    characters = tuple(
        replace(
            character,
            avatar_url=(
                "https://api.dicebear.com/10.x/identicon/png"
                f"?seed={quote(character.name, safe='')}&size=128"
            ),
        )
        for character in DEFAULT_AI_MAID_CHARACTERS
    )
    if override_path is None:
        return CharacterSettings(
            CharacterRoster(DEFAULT_AI_MAID_COMMON_STYLE, characters), {}
        )
    path = override_path
    if not path.exists():
        raise ValueError(f"Character override file does not exist: '{path}'.")
    if not path.is_file():
        raise ValueError(f"Character override path is not a file: '{path}'.")

    override = _read_override(path)
    common_style = (
        DEFAULT_AI_MAID_COMMON_STYLE
        if "common_style" not in override
        else _as_strings(override["common_style"], "common_style")
    )
    if "characters" not in override:
        return CharacterSettings(CharacterRoster(common_style, characters), {})

    character_overrides = _as_object(override["characters"], "characters")
    defaults_by_name = {character.name: character for character in characters}
    unknown_names = set(character_overrides) - set(defaults_by_name)
    if unknown_names:
        names = ", ".join(sorted(unknown_names))
        raise ValueError(f"characters contains unknown names: {names}.")

    characters = tuple(
        _merge_character(
            character,
            character_overrides.get(character.name, {}),
        )
        for character in characters
    )
    mcp_servers: dict[str, tuple[CharacterMcpServer, ...]] = {}
    for name, raw in character_overrides.items():
        values = _as_object(raw, f"characters.{name}")
        servers = _mcp_servers(
            values.get("mcp_servers", {}), f"characters.{name}.mcp_servers"
        )
        if servers:
            mcp_servers[name] = servers
    return CharacterSettings(CharacterRoster(common_style, characters), mcp_servers)


def load_ai_maid_definitions(override_path: Path | None = None) -> CharacterRoster:
    """Load public AI maid definitions from an optional local override."""
    return load_character_settings(override_path).roster

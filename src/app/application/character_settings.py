"""Runtime character settings with optional local overrides."""

import json
from dataclasses import replace
from pathlib import Path
from typing import cast
from urllib.parse import quote, urlsplit

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
    {"position", "responsibilities", "persona", "speech_style", "avatar_url"}
)


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


def load_ai_maid_definitions(
    override_path: Path | None = None,
) -> CharacterRoster:
    """Load default AI maid definitions and apply an optional local override."""
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
        return CharacterRoster(DEFAULT_AI_MAID_COMMON_STYLE, characters)
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
        return CharacterRoster(common_style, characters)

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
    return CharacterRoster(common_style, characters)

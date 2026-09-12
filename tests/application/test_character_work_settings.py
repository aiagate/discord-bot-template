"""Work is opt-in and host paths cannot be supplied through Discord."""

from pathlib import Path

import pytest

from app.application.character_work_settings import CharacterWorkSettings


def _environment(tmp_path: Path) -> dict[str, str]:
    return {
        "CODEX_WORK_ROOT": str(tmp_path / "work"),
        "CODEX_WORK_GUILD_ID": "456",
        "CODEX_WORK_CHANNEL_IDS": "123, 124",
        "CODEX_WORK_USER_IDS": "2",
    }


def test_disabled_work_does_not_read_other_settings(tmp_path: Path) -> None:
    assert CharacterWorkSettings.from_env({}, tmp_path) is None


def test_loads_research_only_defaults(tmp_path: Path) -> None:
    settings = CharacterWorkSettings.from_env(_environment(tmp_path), tmp_path / "bot")
    assert settings is not None
    assert settings.channel_ids == frozenset({"123", "124"})
    assert settings.repository is None
    assert settings.model is None
    assert settings.reasoning_effort is None
    assert settings.timeout_seconds == 1200


def test_loads_model_and_reasoning_effort(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    environment["CODEX_WORK_MODEL"] = "gpt-5.6-luna"
    environment["CODEX_WORK_REASONING_EFFORT"] = "MAX"

    settings = CharacterWorkSettings.from_env(environment, tmp_path / "bot")

    assert settings is not None
    assert settings.model == "gpt-5.6-luna"
    assert settings.reasoning_effort == "max"


def test_channel_ids_are_optional(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    del environment["CODEX_WORK_CHANNEL_IDS"]

    settings = CharacterWorkSettings.from_env(environment, tmp_path / "bot")

    assert settings is not None
    assert settings.channel_ids == frozenset()


def test_reuses_character_guild_when_work_guild_is_not_set(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    del environment["CODEX_WORK_GUILD_ID"]
    environment["DISCORD_CHARACTER_GUILD_ID"] = "789"

    settings = CharacterWorkSettings.from_env(environment, tmp_path / "bot")

    assert settings is not None
    assert settings.guild_id == "789"


def test_prefers_work_guild_override(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    environment["DISCORD_CHARACTER_GUILD_ID"] = "789"

    settings = CharacterWorkSettings.from_env(environment, tmp_path / "bot")

    assert settings is not None
    assert settings.guild_id == "456"


@pytest.mark.parametrize(
    "key,value",
    [
        ("CODEX_WORK_ROOT", "relative"),
        ("CODEX_WORK_GUILD_ID", "456,457"),
        ("CODEX_WORK_USER_IDS", "１２３"),
        ("CODEX_WORK_USER_IDS", "everyone"),
        ("CODEX_WORK_TIMEOUT_SECONDS", "0"),
        ("CODEX_WORK_TIMEOUT_SECONDS", "7201"),
        ("CODEX_WORK_REASONING_EFFORT", "unsupported"),
        ("CODEX_WORK_REPOSITORY", "missing"),
    ],
)
def test_rejects_invalid_settings(tmp_path: Path, key: str, value: str) -> None:
    environment = _environment(tmp_path)
    environment[key] = value
    with pytest.raises(ValueError):
        CharacterWorkSettings.from_env(environment, tmp_path / "bot")


@pytest.mark.parametrize("relative", [".", "..", "workers"])
def test_rejects_root_overlapping_bot(tmp_path: Path, relative: str) -> None:
    environment = _environment(tmp_path)
    environment["CODEX_WORK_ROOT"] = str(tmp_path / "bot" / relative)
    with pytest.raises(ValueError, match="separate"):
        CharacterWorkSettings.from_env(environment, tmp_path / "bot")


def test_source_repository_must_be_outside_work_root(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    repository = tmp_path / "work" / "source"
    repository.mkdir(parents=True)
    environment["CODEX_WORK_REPOSITORY"] = str(repository)
    with pytest.raises(ValueError, match="outside"):
        CharacterWorkSettings.from_env(environment, tmp_path / "bot")
    environment["CODEX_WORK_REPOSITORY"] = str(tmp_path / "bot")
    (tmp_path / "bot").mkdir()
    settings = CharacterWorkSettings.from_env(environment, tmp_path / "bot")
    assert settings is not None
    assert settings.repository == tmp_path / "bot"

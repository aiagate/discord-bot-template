"""Explicit host and Discord settings for optional character work."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


def _ids(value: str) -> frozenset[str]:
    result = frozenset(part.strip() for part in value.split(",") if part.strip())
    if not result or any(
        not item.isascii() or not item.isdecimal() or len(item) > 20 for item in result
    ):
        raise ValueError("Work access settings require Discord IDs.")
    return result


@dataclass(frozen=True, slots=True)
class CharacterWorkSettings:
    """Operator-selected locations and users; Discord cannot override them."""

    root: Path
    guild_id: str
    channel_ids: frozenset[str]
    user_ids: frozenset[str]
    repository: Path | None = None
    model: str | None = None
    timeout_seconds: int = 1200

    @classmethod
    def from_env(
        cls, environment: Mapping[str, str], project_root: Path
    ) -> "CharacterWorkSettings | None":
        """Return disabled before reading other settings when no root is set."""
        root_value = environment.get("CODEX_WORK_ROOT", "").strip()
        if not root_value:
            return None
        root = Path(root_value).expanduser()
        if not root.is_absolute():
            raise ValueError("CODEX_WORK_ROOT must be absolute.")
        root = root.resolve()
        project_root = project_root.resolve()
        if root.is_relative_to(project_root) or project_root.is_relative_to(root):
            raise ValueError("The work root must be separate from the bot repository.")
        guilds = _ids(environment.get("CODEX_WORK_GUILD_ID", ""))
        if len(guilds) != 1:
            raise ValueError("Configure exactly one work guild.")
        repository_value = environment.get("CODEX_WORK_REPOSITORY", "").strip()
        repository = Path(repository_value).expanduser() if repository_value else None
        if repository is not None:
            if not repository.is_absolute() or not repository.is_dir():
                raise ValueError("CODEX_WORK_REPOSITORY must be an existing directory.")
            repository = repository.resolve()
            if root.is_relative_to(repository) or repository.is_relative_to(root):
                raise ValueError("The source repository must be outside the work root.")
        timeout = int(environment.get("CODEX_WORK_TIMEOUT_SECONDS", "") or "1200")
        if not 1 <= timeout <= 7200:
            raise ValueError("Work timeout must be between 1 and 7200 seconds.")
        return cls(
            root=root,
            guild_id=next(iter(guilds)),
            channel_ids=_ids(environment.get("CODEX_WORK_CHANNEL_IDS", "")),
            user_ids=_ids(environment.get("CODEX_WORK_USER_IDS", "")),
            repository=repository,
            model=environment.get("CODEX_WORK_MODEL", "").strip() or None,
            timeout_seconds=timeout,
        )

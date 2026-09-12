"""MCP connection settings shared by configuration and generation adapters."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CharacterMcpServer:
    """Configure one server and its explicitly permitted tools."""

    name: str
    allowed_tools: tuple[str, ...]
    url: str | None = None
    command: str | None = None
    args: tuple[str, ...] = ()
    env_vars: tuple[tuple[str, str], ...] = ()
    headers_env: tuple[tuple[str, str], ...] = ()

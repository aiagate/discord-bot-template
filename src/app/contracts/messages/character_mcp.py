"""MCP configuration and result messages for character tools."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class CharacterMcpServer:
    """Configure one MCP server and its explicitly permitted tools."""

    name: str
    allowed_tools: tuple[str, ...]
    url: str | None = None
    command: str | None = None
    args: tuple[str, ...] = ()
    env_vars: tuple[tuple[str, str], ...] = ()
    headers_env: tuple[tuple[str, str], ...] = ()
    timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        """Validate configuration before it reaches a transport boundary."""
        name = self.name.strip()
        if not name:
            raise ValueError("MCP server name must not be empty.")
        object.__setattr__(self, "name", name)

        tools = tuple(tool.strip() for tool in self.allowed_tools)
        if not tools or any(not tool for tool in tools):
            raise ValueError("MCP server must permit at least one tool.")
        if len(tools) != len(set(tools)):
            raise ValueError("MCP server tools must be unique.")
        object.__setattr__(self, "allowed_tools", tools)

        has_url = self.url is not None
        has_command = self.command is not None
        if has_url == has_command:
            raise ValueError("MCP server requires exactly one URL or command.")

        if self.url is not None:
            url = self.url.strip()
            object.__setattr__(self, "url", url)
            parsed = urlparse(url)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.username is not None
                or parsed.password is not None
            ):
                raise ValueError("MCP server URL must be an HTTP(S) URL.")

        if self.command is not None:
            command = self.command.strip()
            if not command:
                raise ValueError("MCP server command must not be empty.")
            object.__setattr__(self, "command", command)
        if self.timeout_seconds <= 0:
            raise ValueError("MCP server timeout must be greater than zero.")

        object.__setattr__(
            self,
            "env_vars",
            _validate_environment_references(self.env_vars, "environment"),
        )
        object.__setattr__(
            self,
            "headers_env",
            _validate_environment_references(self.headers_env, "header"),
        )


@dataclass(frozen=True, slots=True)
class McpToolDefinition:
    """Provider-neutral metadata for one MCP tool."""

    name: str
    description: str
    input_schema: dict[str, object]
    output_schema: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class McpToolResult:
    """Provider-neutral result returned by an MCP tool call."""

    content: tuple[dict[str, object], ...]
    structured_content: dict[str, object] | None = None
    is_error: bool = False


def _validate_environment_references(
    references: tuple[tuple[str, str], ...], kind: str
) -> tuple[tuple[str, str], ...]:
    """Reject empty or duplicate environment mappings."""
    normalized = tuple((key.strip(), value.strip()) for key, value in references)
    keys = tuple(key for key, _ in normalized)
    values = tuple(value for _, value in normalized)
    if any(not key or not value for key, value in zip(keys, values, strict=True)):
        raise ValueError(f"MCP {kind} environment references must not be empty.")
    comparison_keys = (
        tuple(key.casefold() for key in keys) if kind == "header" else keys
    )
    if len(comparison_keys) != len(set(comparison_keys)):
        raise ValueError(f"MCP {kind} environment keys must be unique.")
    return normalized

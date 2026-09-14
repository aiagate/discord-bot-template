"""MCP tool connection ports."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager

from app.contracts.messages.character_mcp import (
    CharacterMcpServer,
    McpToolDefinition,
    McpToolResult,
)


class McpToolError(Exception):
    """Represent a connection, discovery, or invocation failure."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def __str__(self) -> str:
        """Return the safe error message for application handling."""
        return self.message


class IMcpToolConnection(ABC):
    """Use one connected MCP server within an async context."""

    @abstractmethod
    async def list_tools(self) -> tuple[McpToolDefinition, ...]:
        """List only tools permitted by the server configuration."""
        pass

    @abstractmethod
    async def call_tool(
        self,
        tool_name: str,
        arguments: Mapping[str, object] | None = None,
    ) -> McpToolResult:
        """Call one permitted tool asynchronously.

        A server-declared tool failure is returned with ``is_error=True``;
        transport and validation failures raise ``McpToolError``.
        """
        pass


class IMcpToolConnector(ABC):
    """Open request-scoped connections to configured MCP servers."""

    @abstractmethod
    def connect(
        self, server: CharacterMcpServer
    ) -> AbstractAsyncContextManager[IMcpToolConnection]:
        """Return an async context manager for one MCP server connection."""
        pass

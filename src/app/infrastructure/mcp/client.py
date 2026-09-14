"""MCP client adapter with stdio and Streamable HTTP transports."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from typing import cast

import httpx2
from mcp import Client, StdioServerParameters
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, ContentBlock, Tool

from app.contracts.messages.character_mcp import (
    CharacterMcpServer,
    McpToolDefinition,
    McpToolResult,
)
from app.contracts.ports.mcp_tool_client import (
    IMcpToolConnection,
    IMcpToolConnector,
    McpToolError,
)

DEFAULT_MAX_TOOLS = 64
DEFAULT_MAX_RESULT_CHARS = 32_000


class McpToolConnector(IMcpToolConnector):
    """Connect to MCP servers and expose an allow-listed tool surface."""

    def __init__(
        self,
        *,
        max_tools: int = DEFAULT_MAX_TOOLS,
        max_result_chars: int = DEFAULT_MAX_RESULT_CHARS,
    ) -> None:
        """Create a connector with resource and prompt-size limits."""
        if max_tools <= 0:
            raise ValueError("MCP max_tools must be greater than zero.")
        if max_result_chars <= 0:
            raise ValueError("MCP max_result_chars must be greater than zero.")
        self._max_tools = max_tools
        self._max_result_chars = max_result_chars

    @asynccontextmanager
    async def connect(
        self, server: CharacterMcpServer
    ) -> AsyncIterator[IMcpToolConnection]:
        """Connect, use, and close one MCP server session."""
        if len(server.allowed_tools) > self._max_tools:
            raise McpToolError("MCP permitted tool limit exceeded.")

        async with AsyncExitStack() as stack:
            client = await _connect_client(stack, server)
            yield _McpToolConnection(
                client,
                server,
                max_result_chars=self._max_result_chars,
            )


class _McpToolConnection(IMcpToolConnection):
    """Translate one connected SDK client into application messages."""

    def __init__(
        self,
        client: Client,
        server: CharacterMcpServer,
        *,
        max_result_chars: int,
    ) -> None:
        self._client = client
        self._server = server
        self._max_result_chars = max_result_chars
        self._tools: tuple[McpToolDefinition, ...] | None = None

    async def list_tools(self) -> tuple[McpToolDefinition, ...]:
        """Discover and cache the configured allow-listed tools."""
        if self._tools is not None:
            return self._tools

        try:
            tools = await self._discover_tools()
        except McpToolError:
            raise
        except Exception as error:
            raise McpToolError("Failed to list MCP tools.") from error
        self._tools = tools
        return tools

    async def call_tool(
        self,
        tool_name: str,
        arguments: Mapping[str, object] | None = None,
    ) -> McpToolResult:
        """Call one discovered tool and normalize its result."""
        tools = await self.list_tools()
        if tool_name not in {tool.name for tool in tools}:
            raise McpToolError("MCP tool is not permitted.")

        try:
            result = await self._client.call_tool(
                tool_name,
                dict(arguments or {}),
                read_timeout_seconds=self._server.timeout_seconds,
            )
        except McpToolError:
            raise
        except Exception as error:
            raise McpToolError("MCP tool call failed.") from error
        return _normalize_result(result, self._max_result_chars)

    async def _discover_tools(self) -> tuple[McpToolDefinition, ...]:
        """Read all pages and preserve the configured tool order."""
        allowed = set(self._server.allowed_tools)
        found: dict[str, Tool] = {}
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while True:
            page = await self._client.list_tools(cursor=cursor)
            for tool in page.tools:
                if tool.name not in allowed:
                    continue
                if tool.name in found:
                    raise McpToolError("MCP returned duplicate tool names.")
                found[tool.name] = tool

            next_cursor = page.next_cursor
            if next_cursor is None:
                break
            if next_cursor in seen_cursors:
                raise McpToolError("MCP returned a repeated pagination cursor.")
            seen_cursors.add(next_cursor)
            cursor = next_cursor

        if set(found) != allowed:
            raise McpToolError("MCP server did not provide every permitted tool.")
        return tuple(
            _tool_definition(found[name]) for name in self._server.allowed_tools
        )


async def _connect_client(stack: AsyncExitStack, server: CharacterMcpServer) -> Client:
    """Create and enter the SDK client for one configured transport."""
    try:
        if server.url is not None:
            http_client = await stack.enter_async_context(
                httpx2.AsyncClient(
                    headers=_resolve_environment(server.headers_env),
                    timeout=httpx2.Timeout(server.timeout_seconds),
                )
            )
            transport = streamable_http_client(server.url, http_client=http_client)
            client = Client(
                transport,
                read_timeout_seconds=server.timeout_seconds,
            )
        else:
            if server.command is None:
                raise McpToolError("MCP server requires a URL or command.")
            client = Client(
                StdioServerParameters(
                    command=server.command,
                    args=list(server.args),
                    env=_resolve_environment(server.env_vars),
                ),
                read_timeout_seconds=server.timeout_seconds,
            )
        return await stack.enter_async_context(client)
    except McpToolError:
        raise
    except Exception as error:
        raise McpToolError("Failed to connect to MCP server.") from error


def _resolve_environment(
    references: tuple[tuple[str, str], ...],
) -> dict[str, str]:
    """Resolve secret references without copying the host environment."""
    values: dict[str, str] = {}
    for key, environment_name in references:
        value = os.environ.get(environment_name)
        if not value:
            raise McpToolError(f"MCP requires environment variable {environment_name}.")
        values[key] = value
    return values


def _tool_definition(tool: Tool) -> McpToolDefinition:
    """Convert SDK metadata into a provider-neutral message."""
    return McpToolDefinition(
        name=tool.name,
        description=tool.description or "",
        input_schema=cast(dict[str, object], tool.input_schema),
        output_schema=cast(dict[str, object] | None, tool.output_schema),
    )


def _normalize_result(result: CallToolResult, max_result_chars: int) -> McpToolResult:
    """Convert SDK content blocks while enforcing the result size ceiling."""
    content = tuple(result.content)
    content_payload = tuple(_content_payload(block) for block in content)
    structured_content: object = result.structured_content
    if structured_content is not None and not isinstance(structured_content, dict):
        raise McpToolError("MCP returned invalid structured content.")
    structured = cast(dict[str, object] | None, structured_content)
    is_error = result.is_error
    try:
        serialized = json.dumps(
            {
                "content": content_payload,
                "structured_content": structured,
                "is_error": is_error,
            },
            ensure_ascii=False,
        )
    except (TypeError, ValueError) as error:
        raise McpToolError("MCP returned a non-JSON result.") from error
    if len(serialized) > max_result_chars:
        raise McpToolError("MCP tool result is too large.")
    return McpToolResult(
        content=content_payload,
        structured_content=structured,
        is_error=is_error,
    )


def _content_payload(block: ContentBlock) -> dict[str, object]:
    """Serialize one MCP content block using protocol field aliases."""
    return block.model_dump(mode="json", by_alias=True, exclude_none=True)


__all__ = ["McpToolConnector"]

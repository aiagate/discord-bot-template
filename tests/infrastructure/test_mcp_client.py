"""Tests for the MCP connection adapter."""

import sys
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import anyio
import httpx2
import pytest
from mcp import Client
from mcp.server import MCPServer
from mcp.types import ListToolsResult

from app.contracts.messages.character_mcp import CharacterMcpServer
from app.contracts.ports.mcp_tool_client import McpToolError
from app.infrastructure.mcp import McpToolConnector
from app.infrastructure.mcp import client as mcp_client


@pytest.fixture
def server() -> MCPServer:
    """Create an in-process MCP server for protocol-level tests."""
    server = MCPServer("notes")

    async def read_note(topic: str) -> dict[str, str]:
        """Read one note."""
        return {"topic": topic}

    async def failing_note() -> str:
        """Return an MCP tool error."""
        raise ValueError("not available")

    async def forbidden() -> str:
        """Never expose this tool to the application."""
        raise AssertionError("forbidden tool was called")

    server.add_tool(read_note)
    server.add_tool(failing_note)
    server.add_tool(forbidden)
    return server


@pytest.fixture
def patch_connection(
    monkeypatch: pytest.MonkeyPatch,
    server: MCPServer,
) -> None:
    """Replace the external transport with the official in-process client."""

    async def connect(stack: AsyncExitStack, settings: CharacterMcpServer) -> Client:
        del settings
        return await stack.enter_async_context(Client(server))

    monkeypatch.setattr(mcp_client, "_connect_client", connect)


@pytest.mark.anyio
async def test_connection_discovers_and_calls_only_allowed_tools(
    patch_connection: None,
) -> None:
    """Discovery and invocation stay inside the configured allow-list."""
    connector = McpToolConnector()
    settings = CharacterMcpServer(
        name="notes",
        allowed_tools=("read_note",),
        command="unused",
    )

    async with connector.connect(settings) as connection:
        tools = await connection.list_tools()
        result = await connection.call_tool("read_note", {"topic": "hello"})
        with pytest.raises(McpToolError, match="not permitted"):
            await connection.call_tool("forbidden")

    assert [tool.name for tool in tools] == ["read_note"]
    assert result.structured_content == {"topic": "hello"}
    assert result.is_error is False


@pytest.mark.anyio
async def test_server_tool_error_is_returned_as_a_result(
    patch_connection: None,
) -> None:
    """An MCP tool failure remains available to the model as an error result."""
    connector = McpToolConnector()
    settings = CharacterMcpServer(
        name="notes",
        allowed_tools=("failing_note",),
        command="unused",
    )

    async with connector.connect(settings) as connection:
        result = await connection.call_tool("failing_note")

    assert result.is_error is True
    assert result.content


@pytest.mark.anyio
async def test_discovery_rejects_missing_and_repeated_pages() -> None:
    """Malformed pagination cannot silently widen or truncate the tool set."""
    settings = CharacterMcpServer(
        name="notes",
        allowed_tools=("read_note",),
        command="unused",
    )
    client = AsyncMock(spec=Client)
    connection = mcp_client._McpToolConnection(
        client,
        settings,
        max_result_chars=100,
    )
    client.list_tools.side_effect = [
        ListToolsResult(tools=[], next_cursor="next"),
        ListToolsResult(tools=[], next_cursor=None),
    ]
    with pytest.raises(McpToolError, match="every permitted"):
        await connection.list_tools()

    connection._tools = None
    client.list_tools.side_effect = [
        ListToolsResult(tools=[], next_cursor="same"),
        ListToolsResult(tools=[], next_cursor="same"),
    ]
    with pytest.raises(McpToolError, match="repeated"):
        await connection.list_tools()


@pytest.mark.anyio
async def test_http_headers_are_loaded_without_inheriting_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HTTP auth is resolved from named variables and not leaked in errors."""
    monkeypatch.setenv("MCP_TOKEN", "private-token")
    monkeypatch.setenv("UNRELATED_TOKEN", "must-not-be-sent")
    captured: dict[str, Any] = {}

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

    class FakeTransport:
        pass

    class FakeSdkClient:
        async def __aenter__(self) -> "FakeSdkClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(mcp_client.httpx2, "AsyncClient", FakeClient)

    def fake_streamable_http_client(*args: object, **kwargs: object) -> FakeTransport:
        del args, kwargs
        return FakeTransport()

    def fake_sdk_client(*args: object, **kwargs: object) -> FakeSdkClient:
        del args, kwargs
        return FakeSdkClient()

    monkeypatch.setattr(
        mcp_client, "streamable_http_client", fake_streamable_http_client
    )
    monkeypatch.setattr(mcp_client, "Client", fake_sdk_client)

    connector = McpToolConnector()
    settings = CharacterMcpServer(
        name="notes",
        allowed_tools=("read_note",),
        url="https://example.com/mcp",
        headers_env=(("Authorization", "MCP_TOKEN"),),
    )
    async with connector.connect(settings):
        pass

    assert captured["headers"] == {"Authorization": "private-token"}
    assert "UNRELATED_TOKEN" not in captured["headers"]


@pytest.mark.anyio
async def test_connection_cleanup_runs_when_use_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Async context cleanup is preserved when a caller cancels its work."""
    closed = False

    async def close_connection(
        stack: AsyncExitStack, settings: CharacterMcpServer
    ) -> Client:
        del settings

        @asynccontextmanager
        async def managed() -> AsyncIterator[Client]:
            nonlocal closed
            async with Client(MCPServer("notes")) as client:
                try:
                    yield client
                finally:
                    closed = True

        return await stack.enter_async_context(managed())

    monkeypatch.setattr(mcp_client, "_connect_client", close_connection)
    connector = McpToolConnector()
    settings = CharacterMcpServer(
        name="notes",
        allowed_tools=("read_note",),
        command="unused",
    )
    with pytest.raises(TimeoutError):
        with anyio.fail_after(0.01):
            async with connector.connect(settings) as connection:
                await anyio.sleep_forever()
                await connection.list_tools()

    assert closed is True


def test_server_configuration_rejects_ambiguous_and_unsafe_sources() -> None:
    """Configuration cannot select two transports or embed URL credentials."""
    with pytest.raises(ValueError, match="exactly one"):
        CharacterMcpServer("notes", ("read_note",))
    with pytest.raises(ValueError, match="exactly one"):
        CharacterMcpServer(
            "notes", ("read_note",), url="https://example.com/mcp", command="python"
        )
    with pytest.raises(ValueError, match="HTTP"):
        CharacterMcpServer("notes", ("read_note",), url="file:///tmp/mcp")
    with pytest.raises(ValueError, match="HTTP"):
        CharacterMcpServer(
            "notes", ("read_note",), url="https://user:secret@example.com/mcp"
        )
    with pytest.raises(ValueError, match="unique"):
        CharacterMcpServer("notes", ("read_note", "read_note"), command="python")


@pytest.mark.anyio
async def test_oversized_result_is_rejected(
    patch_connection: None,
) -> None:
    """Large tool results cannot consume an unbounded prompt budget."""
    connector = McpToolConnector(max_result_chars=1)
    settings = CharacterMcpServer(
        name="notes",
        allowed_tools=("read_note",),
        command="unused",
    )

    async with connector.connect(settings) as connection:
        with pytest.raises(McpToolError, match="too large"):
            await connection.call_tool("read_note", {"topic": "hello"})


@pytest.mark.anyio
@pytest.mark.parametrize("transport", ["stdio", "http"])
async def test_real_mcp_transports(
    monkeypatch: pytest.MonkeyPatch,
    server: MCPServer,
    tmp_path: Path,
    transport: str,
) -> None:
    """Both supported transports complete an asynchronous MCP round trip."""
    connector = McpToolConnector()
    if transport == "stdio":
        script = tmp_path / "server.py"
        script.write_text(
            "from mcp.server import MCPServer\n"
            "server = MCPServer('notes')\n"
            "@server.tool()\n"
            "def read_note(topic: str) -> dict[str, str]:\n"
            "    return {'topic': topic}\n"
            "server.run()\n",
            encoding="utf-8",
        )
        settings = CharacterMcpServer(
            name="notes",
            allowed_tools=("read_note",),
            command=sys.executable,
            args=(str(script),),
        )
        async with connector.connect(settings) as connection:
            result = await connection.call_tool("read_note", {"topic": "hello"})
    else:
        app = server.streamable_http_app(stateless_http=True, json_response=True)
        http_clients: list[httpx2.AsyncClient] = []
        http_client_factory = httpx2.AsyncClient

        def fake_async_client(**kwargs: Any) -> httpx2.AsyncClient:
            client = http_client_factory(
                transport=httpx2.ASGITransport(app=app),
                **kwargs,
            )
            http_clients.append(client)
            return client

        monkeypatch.setattr(mcp_client.httpx2, "AsyncClient", fake_async_client)
        async with app.router.lifespan_context(app):
            settings = CharacterMcpServer(
                name="notes",
                allowed_tools=("read_note",),
                url="http://127.0.0.1:8000/mcp",
            )
            async with connector.connect(settings) as connection:
                result = await connection.call_tool("read_note", {"topic": "hello"})
        assert all(client.is_closed for client in http_clients)

    assert result.structured_content == {"topic": "hello"}

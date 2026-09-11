"""Exercise MCP isolation, tool execution, and transport cleanup."""

import asyncio
import json
import os
import sys
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import anyio
import httpx
import httpx2
import pytest
from flow_res import is_err, is_ok
from google import genai
from google.genai import types
from mcp import Client, ListToolsResult, Tool
from mcp.server import MCPServer

from app.contracts.messages.character_mcp import CharacterMcpServer
from app.infrastructure.gemini import GeminiCharacterResponseGenerator, mcp_tools


def _response(*parts: types.Part) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.ModelContent(parts=list(parts)),
                finish_reason=types.FinishReason.STOP,
            )
        ]
    )


def _call(name: str = "mcp_0_0", topic: str = "hello") -> types.Part:
    return types.Part(
        function_call=types.FunctionCall(
            id="call-1",
            name=name,
            args={"topic": topic},
        ),
        thought_signature=b"signature",
    )


@pytest.fixture
def runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[GeminiCharacterResponseGenerator, AsyncMock, list[str], list[str]]:
    server = MCPServer("notes")
    calls: list[str] = []
    closed: list[str] = []

    async def read_note(topic: str) -> str:
        """Read one note."""
        calls.append(topic)
        if topic == "wait":
            await anyio.sleep_forever()
        if topic == "fail":
            raise ValueError("Note unavailable")
        return topic

    server.add_tool(read_note)

    @asynccontextmanager
    async def connection(name: str) -> AsyncIterator[Client]:
        try:
            async with Client(server) as client:
                yield client
        finally:
            closed.append(name)

    async def connect(stack: AsyncExitStack, settings: CharacterMcpServer) -> Client:
        return await stack.enter_async_context(connection(settings.name))

    monkeypatch.setattr(mcp_tools, "_connect", connect)
    client = MagicMock(spec=genai.Client)
    generate = AsyncMock()
    client.aio.models.generate_content = generate
    generator = GeminiCharacterResponseGenerator(
        client,
        "gemini-3.8-flash",
        mcp_servers={
            "Dorothy": (CharacterMcpServer("notes", ("read_note",), command="unused"),),
            "Eris": (
                CharacterMcpServer("eris-notes", ("read_note",), command="unused"),
            ),
        },
    )
    return generator, generate, calls, closed


@pytest.mark.anyio
async def test_only_the_selected_character_connects_and_tools_keep_history(
    runtime: tuple[GeminiCharacterResponseGenerator, AsyncMock, list[str], list[str]],
) -> None:
    generator, generate, calls, closed = runtime
    generate.side_effect = [
        _response(_call()),
        _response(types.Part.from_text(text='{"content":"hello"}')),
    ]
    result = await generator.generate(
        system_instruction="test", user_content="hello", character_name="Eris"
    )
    assert is_ok(result) and result.value.character_name == "Eris"
    assert calls == ["hello"] and closed == ["eris-notes"]
    contents = generate.await_args_list[1].kwargs["contents"]
    assert contents[1].parts[0].thought_signature == b"signature"
    assert contents[2].parts[0].function_response.id == "call-1"
    assert "hello" in json.dumps(contents[2].parts[0].function_response.response)


@pytest.mark.anyio
async def test_selection_times_and_unconfigured_characters_never_connect(
    runtime: tuple[GeminiCharacterResponseGenerator, AsyncMock, list[str], list[str]],
) -> None:
    generator, generate, calls, closed = runtime
    generate.side_effect = [
        _response(types.Part.from_text(text='{"character_name":"Dorothy"}')),
        _response(types.Part.from_text(text='{"posts":[]}')),
        _response(types.Part.from_text(text='{"content":"hello"}')),
    ]
    assert is_ok(
        await generator.select_character(
            system_instruction="test", user_content="test", character_names=("Dorothy",)
        )
    )
    assert is_ok(
        await generator.generate_times_episode(
            system_instruction="test", user_content="test", character_names=("Dorothy",)
        )
    )
    assert is_ok(
        await generator.generate(
            system_instruction="test", user_content="test", character_name="Mira"
        )
    )
    assert calls == [] and closed == []
    assert all(call.kwargs["config"].tools is None for call in generate.await_args_list)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "parts,expected_calls",
    [
        ([_call("forbidden")], 0),
        ([_call(), _call("forbidden")], 0),
        ([_call()] * 9, 0),
        ([_call()], 8),
    ],
)
async def test_unpermitted_calls_and_call_limits_stop_execution(
    runtime: tuple[GeminiCharacterResponseGenerator, AsyncMock, list[str], list[str]],
    parts: list[types.Part],
    expected_calls: int,
) -> None:
    generator, generate, calls, closed = runtime
    generate.return_value = _response(*parts)
    result = await generator.generate(
        system_instruction="test", user_content="test", character_name="Dorothy"
    )
    assert is_err(result)
    assert len(calls) == expected_calls
    assert closed == ["notes"]


@pytest.mark.anyio
async def test_tool_errors_are_returned_to_the_model(
    runtime: tuple[GeminiCharacterResponseGenerator, AsyncMock, list[str], list[str]],
) -> None:
    generator, generate, _, closed = runtime
    generate.side_effect = [
        _response(_call(topic="fail")),
        _response(types.Part.from_text(text='{"content":"取得できませんでした。"}')),
    ]
    result = await generator.generate(
        system_instruction="test", user_content="test", character_name="Dorothy"
    )
    assert is_ok(result)
    part = generate.await_args_list[1].kwargs["contents"][2].parts[0]
    assert "error" in part.function_response.response
    assert closed == ["notes"]


@pytest.mark.anyio
async def test_oversized_results_stop_generation(
    runtime: tuple[GeminiCharacterResponseGenerator, AsyncMock, list[str], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator, generate, calls, closed = runtime
    monkeypatch.setattr(mcp_tools, "MAX_MCP_RESULT_CHARS", 1)
    generate.return_value = _response(_call())
    result = await generator.generate(
        system_instruction="test", user_content="test", character_name="Dorothy"
    )
    assert is_err(result)
    assert calls == ["hello"] and closed == ["notes"]
    assert generate.await_count == 1


@pytest.mark.anyio
async def test_deadline_covers_mcp_tool_calls_and_cleanup(
    runtime: tuple[GeminiCharacterResponseGenerator, AsyncMock, list[str], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator, generate, _, closed = runtime
    monkeypatch.setattr(
        "app.infrastructure.gemini.character_response_generator.GENERATION_TIMEOUT_SECONDS",
        0.1,
    )
    generate.return_value = _response(_call(topic="wait"))
    result = await generator.generate(
        system_instruction="test", user_content="test", character_name="Dorothy"
    )
    assert is_err(result) and closed == ["notes"]


@pytest.mark.anyio
async def test_cancellation_is_propagated_after_cleanup(
    runtime: tuple[GeminiCharacterResponseGenerator, AsyncMock, list[str], list[str]],
) -> None:
    generator, generate, _, closed = runtime
    generate.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await generator.generate(
            system_instruction="test", user_content="test", character_name="Dorothy"
        )
    assert closed == ["notes"]


@pytest.mark.anyio
async def test_connection_failure_does_not_expose_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        mcp_tools,
        "_connect",
        AsyncMock(side_effect=RuntimeError("https://secret:token@example.com")),
    )
    client = MagicMock(spec=genai.Client)
    generator = GeminiCharacterResponseGenerator(
        client,
        "test",
        mcp_servers={
            "Dorothy": (
                CharacterMcpServer("notes", ("read_note",), url="https://example.com"),
            ),
        },
    )
    result = await generator.generate(
        system_instruction="test", user_content="test", character_name="Dorothy"
    )
    assert is_err(result)
    assert "secret" not in result.error.message and "token" not in result.error.message
    client.aio.models.generate_content.assert_not_called()


@pytest.mark.anyio
async def test_discovery_handles_pagination_and_rejects_missing_tools() -> None:
    client = MagicMock(spec=Client)
    tool = Tool(name="read_note", input_schema={"type": "object"})
    client.list_tools = AsyncMock(
        side_effect=[
            ListToolsResult(tools=[], next_cursor="next"),
            ListToolsResult(tools=[tool]),
        ]
    )
    assert await mcp_tools._allowed_tools(client, ("read_note",)) == [tool]
    client.list_tools.assert_awaited_with(cursor="next")
    client.list_tools.side_effect = None
    client.list_tools.return_value = ListToolsResult(tools=[tool])
    with pytest.raises(ValueError, match="every permitted tool"):
        await mcp_tools._allowed_tools(client, ("missing",))
    client.list_tools.return_value = ListToolsResult(tools=[], next_cursor="same")
    with pytest.raises(ValueError, match="repeated"):
        await mcp_tools._allowed_tools(client, ("read_note",))


@pytest.mark.anyio
@pytest.mark.parametrize("transport", ["stdio", "http"])
async def test_real_mcp_transports_and_genai_round_trip(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    transport: str,
) -> None:
    requests: list[dict[str, Any]] = []
    http_clients: list[httpx2.AsyncClient] = []
    authorization: list[str | None] = []
    monkeypatch.setenv("MCP_TEST_TOKEN", "private-token")
    monkeypatch.setenv("DO_NOT_INHERIT", "private-unrelated-token")

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        parts = (
            _response(_call())
            if len(requests) == 1
            else _response(types.Part.from_text(text='{"content":"hello"}'))
        )
        return httpx.Response(
            200, json=parts.model_dump(mode="json", by_alias=True, exclude_none=True)
        )

    async with AsyncExitStack() as stack:
        if transport == "stdio":
            script = tmp_path / "server.py"
            script.write_text(
                "import os\nfrom mcp.server import MCPServer\n"
                'server = MCPServer("notes")\n'
                "@server.tool()\ndef read_note(topic: str) -> dict[str, str | int]:\n"
                '    """Read one note."""\n'
                '    assert os.environ["MCP_TOKEN"] == "private-token"\n'
                '    assert "DO_NOT_INHERIT" not in os.environ\n'
                '    return {"topic": topic, "pid": os.getpid()}\n'
                "@server.tool()\ndef forbidden() -> str:\n"
                '    """Unpermitted tool."""\n    raise AssertionError("must not run")\n'
                "server.run()\n",
                encoding="utf-8",
            )
            settings = CharacterMcpServer(
                "notes",
                ("read_note",),
                command=sys.executable,
                args=(str(script),),
                env_vars=(("MCP_TOKEN", "MCP_TEST_TOKEN"),),
            )
        else:
            server = MCPServer("notes")

            def read_note(topic: str) -> dict[str, str]:
                """Read one note."""
                return {"topic": topic}

            def forbidden() -> str:
                """Unpermitted tool."""
                raise AssertionError("must not run")

            server.add_tool(read_note)
            server.add_tool(forbidden)

            app = server.streamable_http_app(stateless_http=True, json_response=True)
            await stack.enter_async_context(app.router.lifespan_context(app))
            http_factory = httpx2.AsyncClient

            async def capture(request: httpx2.Request) -> None:
                authorization.append(request.headers.get("Authorization"))

            def http_client(**kwargs: Any) -> httpx2.AsyncClient:
                client = http_factory(
                    transport=httpx2.ASGITransport(app=app),
                    event_hooks={"request": [capture]},
                    **kwargs,
                )
                http_clients.append(client)
                return client

            monkeypatch.setattr(mcp_tools.httpx2, "AsyncClient", http_client)
            settings = CharacterMcpServer(
                "notes",
                ("read_note",),
                url="http://127.0.0.1:8000/mcp",
                headers_env=(("Authorization", "MCP_TEST_TOKEN"),),
            )

        http_transport = await stack.enter_async_context(
            httpx.AsyncClient(transport=httpx.MockTransport(respond))
        )
        client = genai.Client(
            api_key="test",
            http_options=types.HttpOptions(httpx_async_client=http_transport),
        )
        generator = GeminiCharacterResponseGenerator(
            client, "gemini-3.8-flash", mcp_servers={"Dorothy": (settings,)}
        )
        try:
            result = await generator.generate(
                system_instruction="test",
                user_content="hello",
                character_name="Dorothy",
            )
        finally:
            await generator.aclose()
        assert is_ok(result), result
        assert len(requests) == 2
        declaration = requests[0]["tools"][0]["functionDeclarations"]
        assert [tool["name"] for tool in declaration] == ["mcp_0_0"]
        assert (
            requests[1]["contents"][1]["parts"][0]["thoughtSignature"] == "c2lnbmF0dXJl"
        )
        response = requests[1]["contents"][2]["parts"][0]["functionResponse"]
        assert response["id"] == "call-1"
        assert "hello" in json.dumps(response)
        assert "private-token" not in json.dumps(requests)
        if transport == "http":
            assert authorization and all(
                value == "private-token" for value in authorization
            )
            assert all(client.is_closed for client in http_clients)
        else:
            pid = response["response"]["result"]["structuredContent"]["pid"]
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)

import os
from typing import cast

from google import genai
from google.genai import types

from app.core.result import Err, Ok, Result
from app.domain.aggregates.chat_history import ChatMessage, ChatRole
from app.domain.interfaces.ai_service import AIServiceError, IAIService
from app.domain.value_objects.ai_provider import AIProvider


class GeminiService(IAIService):
    """Implementation of AI service using Google Gemini."""

    # SYSTEM_INSTRUCTION moved to database
    # Default instruction should be provided via generate_content argument

    def __init__(self) -> None:
        """Initialize Gemini client."""
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            # We don't raise error here to allow app startup without key,
            # but methods will fail. Ideally valid configuration should be enforced.
            self._client = None
        else:
            self._client = genai.Client(api_key=api_key)
        self._cache_name: str | None = None

    @property
    def provider(self) -> AIProvider:
        return AIProvider.GEMINI

    async def initialize_ai_agent(self) -> None:
        """Initialize AI agent by setting up context caching."""
        if not self._client:
            return

        return  # Cached content is too small. total_token_count=606, min_total_token_count=1024
        try:
            # Check for existing cache
            # Note: The SDK might not support filtering by name directly in check,
            # so we iterate.
            display_name = "Dorothy System Instructions"

            # List caches (async iterator)
            async for cache in await self._client.aio.caches.list():
                if cache.display_name == display_name:
                    self._cache_name = cache.name
                    break

            if not self._cache_name:
                # Cached content initialization logic needs to be revisited for dynamic instructions
                # For now, we skip cache initialization or need to fetch active instruction.
                pass

        except Exception as e:
            # Log error but don't crash app? Or re-raise?
            # For now, just print/log and fallback to no cache
            print(f"Failed to initialize Gemini cache: {e}")
            self._cache_name = None

    async def generate_content(
        self,
        prompt: str,
        history: list[ChatMessage],
        system_instruction: str | None = None,
    ) -> Result[str, AIServiceError]:
        """Generate content from prompt using Gemini."""
        if not self._client:
            return Err(AIServiceError("Gemini API key not configured."))

        try:
            # Map domain history to Gemini history
            gemini_history = [
                types.Content(
                    role="user" if msg.role == ChatRole.USER else "model",
                    parts=[
                        types.Part(text=f"{msg.content} \n {msg.sent_at.display_time}")
                    ],
                )
                for msg in history
            ]

            generate_config = types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(
                    thinking_budget=0  # Disables thinking
                ),
                max_output_tokens=2048,
            )

            if self._cache_name:
                generate_config.cached_content = self._cache_name
            elif system_instruction:
                generate_config.system_instruction = system_instruction

            # Use async client for async operations
            chat = self._client.aio.chats.create(
                # model="gemini-2.5-flash-lite",  # Use consistent model
                model="gemini-3-flash-preview",  # Use consistent model
                history=cast(list[types.ContentOrDict], gemini_history),
                config=generate_config,
            )

            response = await chat.send_message(prompt)

            # Make sure response.text is not None.
            # If it is None (e.g. blocked content), we should probably treat as error.
            if response.text is None:
                return Err(AIServiceError("No content generated (blocked or empty)."))
            return Ok(response.text)
        except Exception as e:
            return Err(AIServiceError(f"Gemini API Error: {str(e)}"))

    # def _sanitize_gemini_schema(self, schema: Any) -> Any:
    #     """Sanitize JSON schema for Gemini API compatibility."""
    #     if not isinstance(schema, dict):
    #         return schema

    #     new_schema = schema.copy()

    #     # Remove unsupported keys
    #     keys_to_remove = ["$schema", "additionalProperties", "additional_properties"]
    #     for key in keys_to_remove:
    #         if key in new_schema:
    #             del new_schema[key]

    #     # Recursively sanitize nested structures
    #     if "properties" in new_schema and isinstance(new_schema["properties"], dict):
    #         for key, value in new_schema["properties"].items():
    #             new_schema["properties"][key] = self._sanitize_gemini_schema(value)

    #     if "items" in new_schema:
    #         if isinstance(new_schema["items"], dict):
    #             new_schema["items"] = self._sanitize_gemini_schema(new_schema["items"])
    #         elif isinstance(new_schema["items"], list):
    #             new_schema["items"] = [
    #                 self._sanitize_gemini_schema(item) for item in new_schema["items"]
    #             ]

    #     for combinator in ["allOf", "anyOf", "oneOf"]:
    #         if combinator in new_schema and isinstance(new_schema[combinator], list):
    #             new_schema[combinator] = [
    #                 self._sanitize_gemini_schema(item)
    #                 for item in new_schema[combinator]
    #             ]

    #     return new_schema

    # async def generate_github_mcp_description(self) -> Result[str, AIServiceError]:
    #     """Generate a description of available GitHub MCP tools."""
    #     token = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")
    #     if not token:
    #         return Err(AIServiceError("GITHUB_PERSONAL_ACCESS_TOKEN not found."))

    #     # Use npx to run the GitHub MCP server
    #     # We assume npx is available in the path
    #     server_params = StdioServerParameters(
    #         command="npx",
    #         args=["-y", "@modelcontextprotocol/server-github"],
    #         env={**os.environ, "GITHUB_PERSONAL_ACCESS_TOKEN": token},
    #     )

    #     try:
    #         async with stdio_client(server_params) as (read, write):
    #             async with ClientSession(read, write) as session:
    #                 await session.initialize()
    #                 tools_result = await session.list_tools()

    #                 # Convert MCP tools to Gemini function declarations
    #                 function_declarations = []
    #                 for tool in tools_result.tools:
    #                     raw_schema = tool.inputSchema
    #                     sanitized_schema = self._sanitize_gemini_schema(raw_schema)

    #                     function_declarations.append(
    #                         types.FunctionDeclaration(
    #                             name=tool.name,
    #                             description=tool.description,
    #                             parameters=sanitized_schema,
    #                         )
    #                     )

    #                 # Create a tool definition for Gemini
    #                 gemini_tool = types.Tool(
    #                     function_declarations=function_declarations
    #                 )

    #                 generate_config = types.GenerateContentConfig(
    #                     tools=[gemini_tool],
    #                     max_output_tokens=4096,  # Allow longer output for description
    #                 )

    #                 # Initialize a new chat just for this request
    #                 chat = self._client.aio.chats.create(
    #                     model="gemini-3-flash-preview",
    #                     config=generate_config,
    #                 )

    #                 prompt = (
    #                     "The following tools are available from the GitHub MCP server. "
    #                     "Please analyze them and explain what capabilities this enables for an AI agent. "
    #                     "Group user-facing features logically and explain how they might be used. "
    #                     "Do not just list the tools, but explain the 'skills' the agent now possesses."
    #                 )

    #                 response = await chat.send_message(prompt)

    #                 if response.text is None:
    #                     return Err(
    #                         AIServiceError(
    #                             "No content generated during MCP description."
    #                         )
    #                     )

    #                 return Ok(response.text)

    #     except Exception:
    #         import traceback

    #         return Err(
    #             AIServiceError(
    #                 f"GitHub MCP Integration Error: {traceback.format_exc()}"
    #             )
    #         )

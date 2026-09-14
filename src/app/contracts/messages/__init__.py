"""Shared application messages."""

from app.contracts.messages.character_mcp import (
    CharacterMcpServer,
    McpToolDefinition,
    McpToolResult,
)
from app.contracts.messages.character_prompt import (
    CharacterConversationContext,
    CharacterConversationMessage,
    CharacterSelectionContext,
    character_profile,
    prompt_datetime,
    prompt_message,
)
from app.contracts.messages.generated_character_response import (
    CharacterSelection,
    GeneratedCharacterResponse,
)
from app.contracts.messages.llm import TextGenerationRequest, TextGenerationResponse
from app.contracts.messages.master_context import (
    MAX_MASTER_CONTEXT_LENGTH,
    UNCONFIGURED_MASTER,
    DiscordMaster,
)
from app.contracts.messages.speech_message import (
    CharacterSpeechMessage,
    PublishedSpeech,
    SpeechDeliveryPlan,
)
from app.contracts.messages.user_events import (
    USER_CREATED_TOPIC,
    UserCreatedEvent,
)

__all__ = [
    "CharacterConversationContext",
    "CharacterConversationMessage",
    "CharacterMcpServer",
    "CharacterSelection",
    "CharacterSelectionContext",
    "CharacterSpeechMessage",
    "DiscordMaster",
    "GeneratedCharacterResponse",
    "MAX_MASTER_CONTEXT_LENGTH",
    "McpToolDefinition",
    "McpToolResult",
    "PublishedSpeech",
    "SpeechDeliveryPlan",
    "TextGenerationRequest",
    "TextGenerationResponse",
    "UNCONFIGURED_MASTER",
    "USER_CREATED_TOPIC",
    "UserCreatedEvent",
    "character_profile",
    "prompt_datetime",
    "prompt_message",
]

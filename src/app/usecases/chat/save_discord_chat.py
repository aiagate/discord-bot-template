"""Save a Discord ChatMessage use case."""

from dataclasses import dataclass
from datetime import datetime

from flow_med import Request, RequestHandler
from flow_res import Err, Ok, Result, is_err
from injector import inject

from app.contracts.ports import IChatHistoryQuery, IUnitOfWork
from app.domain.aggregates.chat_message import ChatMessage
from app.domain.repositories import RepositoryErrorType
from app.domain.value_objects import AuthorKind, ChatPlatform
from app.domain.value_objects.message_content import MessageContent
from app.usecases.result import (
    ErrorType,
    UseCaseError,
    UseCaseResultError,
)


@dataclass(frozen=True)
class SaveChatResult:
    """Saved chat result payload."""

    id: str


@dataclass(frozen=True)
class SaveDiscordChatCommand(Request[Result[SaveChatResult, UseCaseResultError]]):
    """Command to persist a Discord message with its external occurrence time."""

    external_sender_id: str
    guild_id: str
    channel_id: str
    content: str
    occurred_at: datetime
    author_kind: AuthorKind = AuthorKind.USER
    external_message_id: str | None = None
    author_name: str | None = None
    reply_to_external_message_id: str | None = None


class SaveDiscordChatHandler(
    RequestHandler[SaveDiscordChatCommand, Result[SaveChatResult, UseCaseResultError]]
):
    """Handle SaveChatCommand."""

    @inject
    def __init__(
        self,
        uow: IUnitOfWork,
        history_query: IChatHistoryQuery,
    ) -> None:
        self._uow = uow
        self._history_query = history_query

    async def handle(
        self, request: SaveDiscordChatCommand
    ) -> Result[SaveChatResult, UseCaseResultError]:
        """Persist an incoming Discord message."""
        if request.external_message_id is not None:
            existing = await self._history_query.get_by_external_id(
                ChatPlatform.DISCORD, request.external_message_id
            )
            if is_err(existing):
                return Err(existing.error)
            if existing.value is not None:
                return Ok(SaveChatResult(id=existing.value.id.to_primitive()))
        try:
            message = ChatMessage.create_discord(
                guild_id=request.guild_id,
                channel_id=request.channel_id,
                external_sender_id=request.external_sender_id,
                content=MessageContent.text(request.content),
                occurred_at=request.occurred_at,
                author_kind=request.author_kind,
                external_message_id=request.external_message_id,
                author_name=request.author_name,
                reply_to_external_message_id=request.reply_to_external_message_id,
            )
        except (TypeError, ValueError) as error:
            return Err(
                UseCaseError(type=ErrorType.VALIDATION_ERROR, message=str(error))
            )

        async with self._uow:
            repository = self._uow.GetRepository(ChatMessage)
            add_result = await repository.add(message)
            if is_err(add_result) and (
                add_result.error.type is not RepositoryErrorType.ALREADY_EXISTS
                or request.external_message_id is None
            ):
                return Err(add_result.error)
            if not is_err(add_result):
                commit_result = await self._uow.commit()
                if is_err(commit_result):
                    return Err(commit_result.error)
                return Ok(SaveChatResult(id=add_result.value.id.to_primitive()))

        # Another receiver may have persisted the same provider message.
        assert request.external_message_id is not None
        existing = await self._history_query.get_by_external_id(
            ChatPlatform.DISCORD, request.external_message_id
        )
        if is_err(existing):
            return Err(existing.error)
        if existing.value is None:
            return Err(
                UseCaseError(
                    type=ErrorType.UNEXPECTED,
                    message="Conflicting message was not found.",
                )
            )
        return Ok(SaveChatResult(id=existing.value.id.to_primitive()))

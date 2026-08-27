"""Save chat message use case."""

from dataclasses import dataclass
from typing import Protocol, cast, runtime_checkable

from flow_med import Request, RequestHandler
from flow_res import Err, Ok, Result, is_err
from injector import inject

from app.domain.aggregates.chat import DiscordChat
from app.domain.repositories import IUnitOfWork
from app.domain.value_objects.message_content import MessageContent
from app.infrastructure.orm_mapping import ORMMappingRegistry
from app.infrastructure.orm_models.chat_orm import ChatORM
from app.usecases.result import ErrorType, UseCaseError


@runtime_checkable
class _SessionProtocol(Protocol):
    """Subset of async session behavior needed by this use case."""

    def add(self, instance: object) -> None: ...

    async def flush(self) -> None: ...


@dataclass(frozen=True)
class SaveChatResult:
    """Saved chat result payload."""

    id: str


@dataclass(frozen=True)
class SaveDiscordChatCommand(Request[Result[SaveChatResult, UseCaseError]]):
    """Command to persist a chat message."""

    user_id: str
    guild_id: str
    channel_id: str
    content: str


class SaveChatHandler(
    RequestHandler[SaveDiscordChatCommand, Result[SaveChatResult, UseCaseError]]
):
    """Handle SaveChatCommand."""

    @inject
    def __init__(
        self,
        uow: IUnitOfWork,
    ) -> None:
        self._uow = uow

    async def handle(
        self, request: SaveDiscordChatCommand
    ) -> Result[SaveChatResult, UseCaseError]:
        """Persist an incoming Discord DM chat message."""
        async with self._uow:
            add_result = await _save_raw_discord_chat(
                self._uow,
                request.user_id,
                request.guild_id,
                request.channel_id,
                request.content,
            )
            if is_err(add_result):
                return Err(
                    UseCaseError(
                        type=ErrorType.UNEXPECTED,
                        message="Failed to save chat message",
                    )
                )

            commit_result = await self._uow.commit()
            if is_err(commit_result):
                return Err(
                    UseCaseError(
                        type=ErrorType.UNEXPECTED,
                        message="Failed to persist chat message",
                    )
                )

            return Ok(SaveChatResult(id=add_result.value.id.to_primitive()))


async def _save_raw_discord_chat(
    uow: IUnitOfWork,
    user_id: str,
    guild_id: str,
    channel_id: str,
    content: str,
) -> Result[DiscordChat, UseCaseError]:
    """Persist a raw Discord chat row with user scope and role."""
    session = getattr(uow, "_session", None)
    if not isinstance(session, _SessionProtocol):
        return Err(
            UseCaseError(
                type=ErrorType.UNEXPECTED,
                message="Unit of work session is not available",
            )
        )

    chat_orm = cast(
        ChatORM,
        ORMMappingRegistry.to_orm(
            DiscordChat.create(
                guild_id=guild_id,
                channel_id=channel_id,
                message_content=MessageContent.text(content),
            )
        ),
    )
    chat_orm.user_id = user_id
    chat_orm.role = "user"
    session.add(chat_orm)
    await session.flush()
    return Ok(cast(DiscordChat, ORMMappingRegistry.from_orm(chat_orm)))

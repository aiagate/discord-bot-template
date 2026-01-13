from dataclasses import dataclass

from injector import inject

from app.core.mediator import Request, RequestHandler
from app.core.result import Ok, Result
from app.domain.interfaces.event_bus import IEventBus
from app.usecases.result import UseCaseError


@dataclass(frozen=True)
class PublishReceivedMessageCommand(Request[Result[None, UseCaseError]]):
    """Command to publish a received Discord message."""

    author: str
    content: str
    channel_id: int


class PublishReceivedMessageHandler(
    RequestHandler[PublishReceivedMessageCommand, Result[None, UseCaseError]]
):
    """Handler for PublishReceivedMessage command."""

    @inject
    def __init__(self, bus: IEventBus) -> None:
        self.bus = bus

    async def handle(
        self, request: PublishReceivedMessageCommand
    ) -> Result[None, UseCaseError]:
        """Publish the message to the EventBus."""
        await self.bus.publish(
            "discord.message",
            {
                "author": request.author,
                "content": request.content,
                "channel_id": request.channel_id,
            },
        )
        return Ok(None)

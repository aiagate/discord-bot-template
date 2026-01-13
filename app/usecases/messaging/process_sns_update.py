from dataclasses import dataclass
from typing import Any

from app.core.mediator import Request, RequestHandler
from app.core.result import Ok, Result
from app.usecases.result import UseCaseError


@dataclass(frozen=True)
class ProcessSnsUpdateResult:
    content: str | None


@dataclass(frozen=True)
class ProcessSnsUpdateCommand(Request[Result[ProcessSnsUpdateResult, UseCaseError]]):
    """Command to process SNS update."""

    payload: dict[str, Any]


class ProcessSnsUpdateHandler(
    RequestHandler[
        ProcessSnsUpdateCommand, Result[ProcessSnsUpdateResult, UseCaseError]
    ]
):
    """Handler for ProcessSnsUpdate command."""

    async def handle(
        self, request: ProcessSnsUpdateCommand
    ) -> Result[ProcessSnsUpdateResult, UseCaseError]:
        text = request.payload.get("text", "")
        if not text:
            return Ok(ProcessSnsUpdateResult(content=None))

        # Business logic: Format the message
        content = f"👀 Look what I found:\n> {text}"
        return Ok(ProcessSnsUpdateResult(content=content))

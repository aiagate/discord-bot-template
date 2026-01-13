from dataclasses import dataclass
from datetime import UTC, datetime

from injector import inject

from app.core.result import Err, Ok, Result, is_err
from app.domain.aggregates.chat_history import ChatMessage, ChatRole
from app.domain.interfaces.ai_service import IAIService
from app.domain.repositories.interfaces import IUnitOfWork
from app.domain.value_objects import SentAt
from app.mediator import Request, RequestHandler
from app.usecases.result import ErrorType, UseCaseError


@dataclass
class GenerateContentQuery(Request[Result[str, UseCaseError]]):
    """Query to generate content from AI."""

    prompt: str


class GenerateContentHandler(
    RequestHandler[GenerateContentQuery, Result[str, UseCaseError]]
):
    """Handler for GenerateContentQuery."""

    @inject
    def __init__(
        self,
        ai_service: IAIService,
        uow: IUnitOfWork,
    ) -> None:
        self._ai_service = ai_service
        self._uow = uow

    async def handle(self, request: GenerateContentQuery) -> Result[str, UseCaseError]:
        """Handle request."""

        # 1. Get history and save user message (Atomic operation)
        async with self._uow:
            histories_result = await self._uow.chat_history.get_recent_history(
                limit=100
            )
            if is_err(histories_result):
                return Err(
                    UseCaseError(
                        type=ErrorType.UNEXPECTED,
                        message="Failed to retrieve chat history",
                    )
                )
            histories = histories_result.unwrap()

            # 2. Call AI Service (External call, no DB transaction)
            result = await self._ai_service.generate_content(request.prompt, histories)
            if is_err(result):
                return Err(
                    UseCaseError(
                        type=ErrorType.UNEXPECTED,
                        message="Failed to generate content",
                    )
                )
            content = result.unwrap()

            # Save user message
            user_msg = ChatMessage.create(
                role=ChatRole.USER,
                content=request.prompt,
                sent_at=SentAt.from_primitive(datetime.now(UTC)).expect(
                    "SentAt creation failed"
                ),
            )
            await self._uow.chat_history.add(user_msg)

            # 3. Save chat history
            model_msg = ChatMessage.create(
                role=ChatRole.MODEL,
                content=content,
                sent_at=SentAt.from_primitive(datetime.now(UTC)).expect(
                    "SentAt creation failed"
                ),
            )
            await self._uow.chat_history.add(model_msg)
            await self._uow.commit()

            return Ok(content)

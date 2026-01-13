from dataclasses import dataclass

from injector import inject

from app.core.result import Err, Ok, Result, is_err
from app.domain.interfaces.ai_service import IAIService
from app.domain.repositories.interfaces import IUnitOfWork
from app.mediator import Request, RequestHandler
from app.usecases.result import ErrorType, UseCaseError


@dataclass
class GenerateContentWithoutLeanQuery(Request[Result[str, UseCaseError]]):
    """Query to generate content from AI."""

    prompt: str


class GenerateContentWithoutLeanHandler(
    RequestHandler[GenerateContentWithoutLeanQuery, Result[str, UseCaseError]]
):
    """Handler for GenerateContentWithoutLeanQuery."""

    @inject
    def __init__(
        self,
        ai_service: IAIService,
        uow: IUnitOfWork,
    ) -> None:
        self._ai_service = ai_service
        self._uow = uow

    async def handle(
        self, request: GenerateContentWithoutLeanQuery
    ) -> Result[str, UseCaseError]:
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

            return Ok(content)

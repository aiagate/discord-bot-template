from dataclasses import dataclass
from datetime import UTC, datetime

from injector import inject

from app.core.result import Err, Ok, Result, is_err
from app.domain.aggregates.chat_history import ChatMessage, ChatRole
from app.domain.aggregates.system_instruction import SystemInstruction
from app.domain.interfaces.ai_service import IAIService
from app.domain.repositories.interfaces import IUnitOfWork
from app.domain.value_objects import SentAt
from app.mediator import Request, RequestHandler
from app.usecases.result import ErrorType, UseCaseError

# Hardcoded channel ID for MVP
TARGET_CHANNEL_ID = "786125475151216652"


@dataclass
class SpontaneousDialogCommand(Request[Result[tuple[str, str], UseCaseError]]):
    """Command to trigger spontaneous dialog."""

    pass


class SpontaneousDialogHandler(
    RequestHandler[SpontaneousDialogCommand, Result[tuple[str, str], UseCaseError]]
):
    """Handler for SpontaneousDialogCommand."""

    @inject
    def __init__(
        self,
        ai_service: IAIService,
        uow: IUnitOfWork,
    ) -> None:
        self._ai_service = ai_service
        self._uow = uow

    async def handle(
        self, request: SpontaneousDialogCommand
    ) -> Result[tuple[str, str], UseCaseError]:
        """Handle request."""

        # 1. Get recent context
        async with self._uow:
            histories_result = await self._uow.GetRepository(
                ChatMessage
            ).get_recent_history(limit=20)

            if is_err(histories_result):
                return Err(
                    UseCaseError(
                        type=ErrorType.UNEXPECTED,
                        message="Failed to retrieve chat history",
                    )
                )
            histories = histories_result.unwrap()

            # 2. Prepare Prompt
            # The prompt is internal instruction to the bot to start talking.
            # We don't save this prompt to the user history.
            internal_prompt = (
                "# Role & Tone"
                "- あなたはおしゃべりがしたい気分です。"
                "- 口調：カジュアルで親しみやすい言葉遣い（堅苦しい「です・ます」調よりも、少し砕けた表現や話し言葉を使用）。"
                ""
                "# Task"
                "ユーザーとの会話を開始するための短いメッセージを生成してください。"
                ""
                "# Topic Selection Strategy"
                "1. 以前の会話の内容や流れに関連した話題を振る。"
                "2.「テクノロジー」「AI」「ゲーム」に関連する面白いトピックをランダムに一つ選んで話題にする。"
                ""
                "# Negative Constraints"
                "- 毎回「こんにちは」「ハロー」などの定型的な挨拶で文を始めないこと。"
                "- 長文になりすぎないこと。"
            )

            # 3. Call AI Service
            instruction_result = await self._uow.GetRepository(
                SystemInstruction
            ).find_active_by_provider(self._ai_service.provider)

            active_instruction = None
            if not is_err(instruction_result):
                active_instruction = instruction_result.unwrap()

            instruction_text = (
                active_instruction.instruction if active_instruction else None
            )

            result = await self._ai_service.generate_content(
                internal_prompt, histories, system_instruction=instruction_text
            )

            if is_err(result):
                return Err(
                    UseCaseError(
                        type=ErrorType.UNEXPECTED,
                        message=f"Failed to generate content: {result.error}",
                    )
                )
            content = result.unwrap()

            # 4. Save ONLY the Model message
            model_msg = ChatMessage.create(
                role=ChatRole.MODEL,
                content=content,
                sent_at=SentAt.from_primitive(datetime.now(UTC)).expect(
                    "SentAt creation failed"
                ),
            )
            await self._uow.GetRepository(ChatMessage).add(model_msg)
            await self._uow.commit()

            return Ok((content, TARGET_CHANNEL_ID))

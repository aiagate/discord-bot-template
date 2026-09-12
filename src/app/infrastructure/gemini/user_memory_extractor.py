"""Gemini adapter for conservative user-memory extraction."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

from flow_res import Err, Ok, Result
from google import genai
from google.genai import types

from app.contracts.messages.user_memory import (
    UserMemoryExtractionRequest,
    UserMemoryExtractionResult,
)
from app.contracts.ports.user_memory import (
    IUserMemoryExtractor,
    MemoryExtractionError,
)

logger = logging.getLogger(__name__)
EXTRACTION_TIMEOUT_SECONDS = 90.0
MAX_OUTPUT_TOKENS = 4096

_SYSTEM_INSTRUCTION = """あなたは会話ログから長期記憶を整理する抽出器です。
入力には1人のcanonical Userに紐づく、過去のraw chatだけが含まれます。
ユーザー本人の発言を根拠に、将来も役立つ安定した事実・好み・決定をProfileへ、
その日の意味のある出来事をTimelineへ抽出してください。

厳守事項:
- raw_logsの全message_idをsource_evaluationsに必ず一度ずつ含める。
- 根拠のない推測、秘密、認証情報、健康・金融などのセンシティブな推定は保存しない。
- 他人、bot、webhookの発言からユーザーの属性を推定しない。
- Profile/Timelineのsource_message_idsにはuser本人の発言IDだけを使い、botの発言は文脈に限る。
- 確信が持てない情報はdeferred、保存価値がない雑談はnot_memorableにする。
- Profile/Timelineのsource_message_idsはdispositionがusedのIDだけを使う。
- 既存Profileを訂正するときだけreplace、それ以外はmergeを使う。
- Profileのsummary・traits・preferencesは短く、重複を避ける。
- 返却JSON以外の文章は出力しない。
"""


def _json_default(value: object) -> str:
    """Serialize timestamps in the extractor request."""
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


def _request_payload(request: UserMemoryExtractionRequest) -> str:
    """Build a bounded, explicit JSON input for Gemini."""
    return json.dumps(
        {
            "day": request.day,
            "raw_logs": [
                {
                    "message_id": log.message_id,
                    "platform": log.platform,
                    "author_kind": log.author_kind,
                    "content": log.content,
                    "occurred_at": log.occurred_at,
                }
                for log in request.raw_logs
            ],
            "existing_profile": (
                {
                    "summary": request.existing_profile.summary,
                    "traits": request.existing_profile.traits,
                    "preferences": request.existing_profile.preferences,
                    "confidence": request.existing_profile.confidence,
                }
                if request.existing_profile is not None
                else None
            ),
            "existing_timeline": [
                {
                    "day": entry.day,
                    "title": entry.title,
                    "summary": entry.summary,
                    "occurred_at": entry.occurred_at,
                }
                for entry in request.existing_timeline
            ],
        },
        ensure_ascii=False,
        default=_json_default,
    )


class GeminiUserMemoryExtractor(IUserMemoryExtractor):
    """Extract strict Profile and Timeline patches with Gemini structured output."""

    def __init__(
        self,
        client: genai.Client,
        model: str,
        *,
        max_output_tokens: int = MAX_OUTPUT_TOKENS,
    ) -> None:
        """Initialize the extractor with a configured Gemini client."""
        self._client = client
        self._model = model
        self._max_output_tokens = max_output_tokens

    async def extract(
        self, request: UserMemoryExtractionRequest
    ) -> Result[UserMemoryExtractionResult, MemoryExtractionError]:
        """Call Gemini and validate its complete source disposition."""
        try:
            config = types.GenerateContentConfig(
                system_instruction=_SYSTEM_INSTRUCTION,
                max_output_tokens=self._max_output_tokens,
                response_mime_type="application/json",
                response_schema=UserMemoryExtractionResult,
            )
            async with asyncio.timeout(EXTRACTION_TIMEOUT_SECONDS):
                response = await self._client.aio.models.generate_content(
                    model=self._model,
                    contents=_request_payload(request),
                    config=config,
                )
            text = response.text
            if text is None or not text.strip():
                raise ValueError("Gemini returned an empty memory extraction.")
            return Ok(UserMemoryExtractionResult.model_validate_json(text))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.error("Gemini user memory extraction failed: %s", error)
            return Err(MemoryExtractionError(message=str(error)))

    async def aclose(self) -> None:
        """Close the underlying Gemini client."""
        try:
            await self._client.aio.aclose()
        finally:
            self._client.close()


__all__ = ["GeminiUserMemoryExtractor"]

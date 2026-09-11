"""Generate and deliver a Times episode for one saved trigger message."""

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from flow_med import Request, RequestHandler
from flow_res import Err, Ok, Result, is_err
from injector import inject

from app.contracts.messages.character_prompt import (
    MASTER_CONTEXT_INSTRUCTION,
    TIME_CONTEXT_INSTRUCTION,
    UNCONFIGURED_MASTER,
    DiscordMaster,
    character_profile,
    prompt_datetime,
    prompt_message,
)
from app.contracts.messages.times_message import TimesEpisodePlan
from app.contracts.ports import IChatHistoryQuery
from app.contracts.ports.character_response_generator import (
    ICharacterResponseGenerator,
)
from app.contracts.ports.times_episode_store import ITimesEpisodeStore
from app.contracts.ports.times_publisher import ITimesPublisher
from app.domain.aggregates.chat_message import ChatMessage
from app.domain.characters import CharacterRoster
from app.domain.value_objects import (
    ChatPlatform,
    DiscordConversationScope,
)
from app.usecases.result import ErrorType, UseCaseError, UseCaseResultError

TIMES_HISTORY_LIMIT = 20
TIMES_MEMORY_LIMIT = 5
HISTORY_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class GenerateTimesEpisodeCommand(Request[Result[None, UseCaseResultError]]):
    """Trigger an episode using a Discord message ID and an explicit delivery channel."""

    source_message_id: str
    guild_id: str
    channel_id: str
    delivery_channel_id: str


def _build_times_instruction(roster: CharacterRoster) -> str:
    """Build the instruction for generating Times board episodes."""
    profiles = [character_profile(character) for character in roster.characters]
    return "\n".join(
        (
            "あなたはDiscord上の共有掲示板（Times）で会話・つぶやきを投稿するAIキャラクター（AIメイド）たちです。",
            "ユーザーの会話を受けて、メイド同士の会話・ツッコミ・意見交換を多めにしてください。"
            "仲間の発言に反応し、各自の名前・役職・個性を保ってください。",
            "1回の呼び出しで、0件以上の投稿（posts）を時系列順に返してください。",
            "1エピソードの投稿数は多くても12件までに抑えてください。",
            "特に反応する必要がない場合や無駄口を挟むべきでない場合は、postsを空配列 [] にしてください。",
            "各投稿には必ず発言キャラクターの名前（character_name）と本文（content）を含めてください。",
            "本文には名前・役職の見出しや区切り線を含めず、発言内容だけを書いてください。",
            "board_memory は過去のTimes掲示板の完了投稿履歴です。これはキャラクター同士の過去の雑談やメモであり、ユーザーに関する絶対的な事実や確定情報ではありません。",
            "board_memoryのcreated_atはエピソードの作成日時で、各投稿の送信時刻ではありません。nullなら日時は不明です。",
            "source_history はDiscordの対象チャンネルにおける過去の会話履歴、current は今回のトリガーとなった最新メッセージです。",
            "事実部分は source_history と current に実際に出た内容だけに限定し、"
            "未確認の出来事を補わないでください。",
            "「次にこれが来そう」などの推測は可ですが、推測だと分かる表現にし、"
            "board_memory 内の推測も事実として扱わないでください。",
            "共通ルール:",
            *roster.common_style,
            MASTER_CONTEXT_INSTRUCTION,
            TIME_CONTEXT_INSTRUCTION,
            "Times専用上書き: 通常応答の単一話者・他のメイドの台詞を代作しない制約は適用しません。"
            "1エピソードに複数のメイドが発言し、posts配列で掛け合いを生成してください。",
            "キャラクター一覧:",
            json.dumps(profiles, ensure_ascii=False),
        )
    )


def _build_times_context(
    history: Sequence[ChatMessage],
    source: ChatMessage,
    content: str,
    board_memory: Sequence[TimesEpisodePlan],
    *,
    master: DiscordMaster,
) -> str:
    return json.dumps(
        {
            "master": master.to_prompt(),
            "board_memory": [
                {
                    "source_message_id": episode.source_message_id,
                    "created_at": prompt_datetime(episode.created_at)
                    if episode.created_at is not None
                    else None,
                    "posts": [
                        {
                            "character_name": post.character_name,
                            "content": post.content,
                        }
                        for post in episode.posts
                    ],
                }
                for episode in board_memory
                if episode.posts
            ],
            "source_history": [prompt_message(message) for message in history],
            "current": prompt_message(source, content),
        },
        ensure_ascii=False,
    )


def _failure(message: str, public_message: str) -> Err[UseCaseResultError]:
    return Err(
        UseCaseError(
            type=ErrorType.UNEXPECTED, message=message, public_message=public_message
        )
    )


class GenerateTimesEpisodeHandler(
    RequestHandler[GenerateTimesEpisodeCommand, Result[None, UseCaseResultError]]
):
    """Generate and deliver a Times episode with continuity and recovery."""

    @inject
    def __init__(
        self,
        generator: ICharacterResponseGenerator,
        publisher: ITimesPublisher,
        times_store: ITimesEpisodeStore,
        history_query: IChatHistoryQuery,
        roster: CharacterRoster,
        master: DiscordMaster = UNCONFIGURED_MASTER,
    ) -> None:
        self._generator = generator
        self._publisher = publisher
        self._times_store = times_store
        self._history_query = history_query
        self._roster = roster
        self._master = master

    async def handle(
        self, request: GenerateTimesEpisodeCommand
    ) -> Result[None, UseCaseResultError]:
        """Generate from the source snapshot or deliver an existing pending plan."""
        scope = DiscordConversationScope(
            guild_id=request.guild_id, channel_id=request.channel_id
        )

        source_result = await self._history_query.get_by_external_id(
            ChatPlatform.DISCORD, request.source_message_id
        )
        if is_err(source_result):
            return Err(source_result.error)
        source = source_result.value
        if source is None or source.external_message_id is None:
            return Err(
                UseCaseError(
                    type=ErrorType.VALIDATION_ERROR,
                    message="Invalid or missing source message identity.",
                )
            )
        if source.conversation_scope != scope:
            return Err(
                UseCaseError(
                    type=ErrorType.VALIDATION_ERROR,
                    message="Source message does not belong to this Discord conversation.",
                )
            )

        external_id = source.external_message_id
        existing_res = await self._times_store.get(external_id)
        if is_err(existing_res):
            return _failure(
                existing_res.error.message, "Times計画の取得に失敗しました。"
            )

        existing_plan = existing_res.value
        if existing_plan is not None:
            if existing_plan.delivery_channel_id != request.delivery_channel_id:
                return Err(
                    UseCaseError(
                        type=ErrorType.VALIDATION_ERROR,
                        message="Times episode belongs to another delivery channel.",
                    )
                )
            if existing_plan.status == "COMPLETED" or existing_plan.complete:
                return Ok(None)
            if existing_plan.failure is not None:
                return _failure(
                    existing_plan.failure, "Times投稿の配信に失敗しました。"
                )
            if existing_plan.posts:
                delivered = await self._publisher.deliver(existing_plan)
                if is_err(delivered):
                    return _failure(
                        delivered.error.message, "Times投稿の送信に失敗しました。"
                    )
                return Ok(None)
            plan = existing_plan
        else:
            plan = TimesEpisodePlan(
                source_message_id=external_id,
                guild_id=scope.guild_id,
                channel_id=scope.channel_id,
                delivery_channel_id=request.delivery_channel_id,
                posts=(),
                status="PENDING",
                next_post_index=0,
                created_at=datetime.now(UTC),
            )
            saved_initial = await self._times_store.save(plan)
            if is_err(saved_initial):
                return _failure(
                    saved_initial.error.message, "Times計画の保存に失敗しました。"
                )

        try:
            async with asyncio.timeout(HISTORY_TIMEOUT_SECONDS):
                history_result = await self._history_query.get_recent_history(
                    scope,
                    limit=TIMES_HISTORY_LIMIT,
                    before=(source.occurred_at, source.id.to_primitive()),
                )
        except (ValueError, TimeoutError) as error:
            return _failure(str(error), "会話履歴の取得に失敗しました。")
        if is_err(history_result):
            return _failure(
                history_result.error.message, "会話履歴の取得に失敗しました。"
            )

        try:
            async with asyncio.timeout(HISTORY_TIMEOUT_SECONDS):
                memory_result = await self._times_store.get_recent_completed(
                    DiscordConversationScope(
                        guild_id=request.guild_id,
                        channel_id=request.delivery_channel_id,
                    ),
                    limit=TIMES_MEMORY_LIMIT,
                    before=plan.created_at,
                )
        except (ValueError, TimeoutError) as error:
            return _failure(str(error), "Times記憶の取得に失敗しました。")
        if is_err(memory_result):
            return _failure(
                memory_result.error.message, "Times記憶の取得に失敗しました。"
            )

        character_names = tuple(character.name for character in self._roster.characters)
        if not character_names:
            return _failure(
                "No AI characters configured.", "AIの設定に問題があります。"
            )

        instruction = _build_times_instruction(self._roster)
        user_content = _build_times_context(
            history_result.value,
            source,
            str(source.content.payload.get("text", "")),
            memory_result.value,
            master=self._master,
        )

        generated = await self._generator.generate_times_episode(
            system_instruction=instruction,
            user_content=user_content,
            character_names=character_names,
        )
        if is_err(generated):
            return _failure(
                generated.error.message,
                "Timesエピソードの生成に失敗しました。",
            )

        posts = generated.value
        plan = replace(
            plan,
            posts=posts,
            status="DELIVERING" if posts else "COMPLETED",
            next_post_index=0,
            next_chunk_index=0,
        )
        saved_plan = await self._times_store.save(plan)
        if is_err(saved_plan):
            return _failure(saved_plan.error.message, "Times計画の保存に失敗しました。")
        if not posts:
            return Ok(None)

        delivered = await self._publisher.deliver(plan)
        if is_err(delivered):
            return _failure(delivered.error.message, "Times投稿の送信に失敗しました。")
        return Ok(None)

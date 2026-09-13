"""Local control and unattended operation of the support collective."""

import argparse
import asyncio
import json
import logging
import math
import os
import time
from pathlib import Path

from app.contracts.messages.support import RuntimeObservation
from app.contracts.ports.conversation import ConversationThinker
from app.infrastructure.codex import CodexThinker
from app.infrastructure.communication import FilePublisher, GeminiSpeaker
from app.infrastructure.conversation import (
    GeminiConversationThinker,
    OpenAIConversationThinker,
)
from app.infrastructure.store import LocalStore, atomic_write, runner_lock
from app.usecases.conversation import ConversationRunner
from app.usecases.support import Communicator, SupportRunner

logger = logging.getLogger(__name__)


def parser() -> argparse.ArgumentParser:
    """Define purpose, input, observation, lifecycle, and runtime controls."""
    result = argparse.ArgumentParser(description="自律的に支援を続けるAI集団")
    result.add_argument(
        "--root", type=Path, default=Path(".collective"), help="支援状態・記憶の保存先"
    )
    sub = result.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="初期設定を作成")
    init.add_argument("--master-file", type=Path, help="マスターの思想・希望のMarkdown")
    add = sub.add_parser("add", help="継続する支援方針を登録")
    add.add_argument("objective", help="実現したい目的")
    add.add_argument(
        "--criterion",
        action="append",
        required=True,
        help="達成を確かめる条件（複数指定可）",
    )
    add.add_argument("--scope", required=True, help="支援対象・参照場所・任せる範囲")
    add.add_argument("--character", default="dorothy")
    add.add_argument(
        "--repo", action="append", default=[], help="担当者別に取得するリポジトリURL"
    )
    add.add_argument("--budget", type=int, default=24, help="今回任せる実行回数")
    for command, help_text in (
        ("say", "通常の会話を追加"),
        ("note", "マスターの原文を追加"),
        ("observe", "観測した情報を追加"),
    ):
        note = sub.add_parser(command, help=help_text)
        note.add_argument("activity")
        note.add_argument("content")
        note.add_argument("--key", help="同じ入力の重複を防ぐ識別子")
    status = sub.add_parser("status", help="支援の目的・状態・次の一手を確認")
    status.add_argument("activity", nargs="?")
    sub.add_parser("pending", help="未配信の発言と送信確認の状態を表示")
    history = sub.add_parser("history", help="発言・実行・判断の根拠を確認")
    history.add_argument("activity")
    stop = sub.add_parser(
        "stop", help="新しい実行を停止し、実行中の担当者にも停止を伝える"
    )
    stop.add_argument("activity")
    resume = sub.add_parser("resume", help="支援を明示的に再開")
    resume.add_argument("activity")
    resume.add_argument("--budget", type=int, help="追加する実行回数")
    for command in ("run", "discord"):
        run = sub.add_parser(
            command, help="自律実行" if command == "run" else "Discordを窓口に自律実行"
        )
        run.add_argument("--model", default=os.environ.get("COLLECTIVE_CODEX_MODEL"))
        run.add_argument("--timeout", type=float, default=1200)
        run.add_argument("--interval", type=float, default=10)
        if command == "run":
            run.add_argument(
                "--once", action="store_true", help="実行可能な支援を一回進める"
            )
        else:
            run.add_argument(
                "--activity", required=True, help="通常の発言を届ける支援活動"
            )
            run.add_argument("--channel-id", type=int, required=True)
            run.add_argument("--master-id", type=int, required=True)
    return result


def make_speaker() -> GeminiSpeaker | None:
    """Enable expression by its model setting, independently of conversation."""
    key = os.environ.get("GEMINI_API_KEY")
    model = os.environ.get("COLLECTIVE_GEMINI_MODEL")
    if model and not key:
        raise ValueError(
            "Geminiを使う場合はGEMINI_API_KEYとCOLLECTIVE_GEMINI_MODELを設定してください。"
        )
    return GeminiSpeaker(key, model) if key and model else None


def make_conversation_thinker() -> ConversationThinker:
    """Select a provider and model only at the application composition boundary."""
    provider = os.environ.get("COLLECTIVE_CONVERSATION_PROVIDER", "gemini")
    model = os.environ.get("COLLECTIVE_CONVERSATION_MODEL")
    if provider == "gemini":
        key = os.environ.get("GEMINI_API_KEY")
        model = model or os.environ.get("COLLECTIVE_GEMINI_MODEL")
        if not key or not model:
            raise ValueError("会話用GeminiのAPIキーとモデル名を設定してください。")
        return GeminiConversationThinker(key, model)
    if provider == "openai":
        key = os.environ.get("OPENAI_API_KEY")
        if not key or not model:
            raise ValueError("会話用OpenAIのAPIキーとモデル名を設定してください。")
        return OpenAIConversationThinker(key, model)
    raise ValueError("会話の提供元はgeminiまたはopenaiを指定してください。")


async def serve(
    runner: SupportRunner,
    communicator: Communicator,
    store: LocalStore,
    *,
    interval: float,
    once: bool = False,
    conversation: ConversationRunner | None = None,
) -> None:
    """Advance work and deliver notices in independent loops."""
    if once:
        if conversation is not None:
            await conversation.tick()
        await runner.tick()
        store.project()
        await communicator.flush()
        return

    async def work_loop() -> None:
        while True:
            try:
                progressed = await runner.tick()
                store.project()
            except Exception:
                logger.exception("State or projection unavailable; retrying")
                progressed = False
            await asyncio.sleep(0 if progressed else interval)

    async def communication_loop() -> None:
        while True:
            try:
                await communicator.flush()
            except Exception:
                logger.exception("Communication unavailable; work continues")
            await asyncio.sleep(interval)

    async def conversation_loop() -> None:
        assert conversation is not None
        while True:
            try:
                progressed = await conversation.tick()
                store.project()
            except Exception:
                logger.exception("Conversation pending; autonomous work continues")
                progressed = False
            await asyncio.sleep(0 if progressed else interval)

    async with asyncio.TaskGroup() as group:
        group.create_task(work_loop())
        group.create_task(communication_loop())
        if conversation is not None:
            group.create_task(conversation_loop())


async def run(store: LocalStore, args: argparse.Namespace) -> None:
    """Compose local adapters without coupling use cases to their providers."""
    if any(
        not math.isfinite(value) or value <= 0
        for value in (args.interval, args.timeout)
    ):
        raise ValueError("実行間隔と制限時間は0より大きい有限の値にしてください。")
    if args.command == "run" and store.discord_destination() is not None:
        raise ValueError(
            "この保存先はDiscordに紐付いています。discordコマンドを使ってください。"
        )
    speaker = make_speaker()
    conversation_thinker: ConversationThinker | None = None
    runner = SupportRunner(store, CodexThinker(args.model), timeout=args.timeout)
    try:
        if (
            args.command == "discord"
            or store.pending_conversation() is not None
            or os.environ.get("COLLECTIVE_CONVERSATION_MODEL")
            or os.environ.get("COLLECTIVE_GEMINI_MODEL")
        ):
            conversation_thinker = make_conversation_thinker()
        conversation = (
            ConversationRunner(store, conversation_thinker)
            if conversation_thinker is not None
            else None
        )
        with runner_lock(store.root):
            store.recover()
            store.observe(
                RuntimeObservation(
                    component="configuration",
                    status="configured",
                    observed_at=time.time(),
                    source="cli.run",
                    settings={
                        "gemini_credentials": bool(os.environ.get("GEMINI_API_KEY")),
                        "openai_credentials": bool(os.environ.get("OPENAI_API_KEY")),
                        "discord_credentials": bool(
                            os.environ.get("DISCORD_BOT_TOKEN")
                        ),
                        "webhook_credentials": bool(
                            os.environ.get("DISCORD_WEBHOOK_URL")
                        ),
                        "expression_enabled": speaker is not None,
                        "conversation_enabled": conversation is not None,
                        "discord_enabled": args.command == "discord",
                    },
                )
            )
            if args.command == "discord":
                from app.infrastructure.discord import DiscordGateway
                from app.infrastructure.webhook import DiscordWebhookPublisher

                token = os.environ.get("DISCORD_BOT_TOKEN")
                if not token:
                    raise ValueError("DISCORD_BOT_TOKENを設定してください。")
                webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
                if not webhook_url:
                    raise ValueError("DISCORD_WEBHOOK_URLを設定してください。")
                gateway = DiscordGateway(
                    store, args.activity, args.channel_id, args.master_id
                )
                async with gateway:
                    await gateway.login(token)
                    publisher = DiscordWebhookPublisher(
                        store, gateway, webhook_url, args.channel_id
                    )
                    await publisher.initialize()
                    communicator = Communicator(store, publisher, speaker)
                    async with asyncio.TaskGroup() as group:
                        group.create_task(gateway.connect(reconnect=True))
                        group.create_task(
                            serve(
                                runner,
                                communicator,
                                store,
                                interval=args.interval,
                                conversation=conversation,
                            )
                        )
            else:
                communicator = Communicator(
                    store, FilePublisher(store.root / "messages"), speaker
                )
                await serve(
                    runner,
                    communicator,
                    store,
                    interval=args.interval,
                    once=args.once,
                    conversation=conversation,
                )
    finally:
        if conversation_thinker is not None:
            await conversation_thinker.close()
        if speaker is not None:
            await speaker.close()


def main(argv: list[str] | None = None) -> None:
    """Operate from a terminal with local delivery by default."""
    args = parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    store = LocalStore(args.root)
    try:
        if args.command == "init":
            store.initialize()
            if args.master_file is not None:
                atomic_write(
                    store.root / "master.md",
                    args.master_file.read_text(encoding="utf-8"),
                )
            print(store.root)
        elif args.command == "add":
            activity = store.create(
                args.objective,
                tuple(args.criterion),
                args.scope,
                args.character,
                repositories=tuple(args.repo),
                max_runs=args.budget,
            )
            print(activity.id)
        elif args.command == "say":
            store.receive(args.activity, args.content, external_key=args.key)
        elif args.command in {"note", "observe"}:
            store.inform(
                args.activity,
                args.content,
                observation=args.command == "observe",
                external_key=args.key,
            )
        elif args.command in {"stop", "resume"}:
            store.control(
                args.activity,
                resume=args.command == "resume",
                budget=getattr(args, "budget", None),
            )
        elif args.command == "status":
            activities = (
                (store.current(args.activity),) if args.activity else store.activities()
            )
            for activity in activities:
                print(activity.model_dump_json(indent=2))
        elif args.command == "history":
            store.current(args.activity)
            for event in store.events(args.activity):
                print(event.model_dump_json())
        elif args.command == "pending":
            for notice in store.pending_notices():
                attempt = store.discord_attempt(notice.id)
                print(
                    json.dumps(
                        {
                            "notice": notice.model_dump(),
                            "attempt": attempt.model_dump() if attempt else None,
                        },
                        ensure_ascii=False,
                    )
                )
        else:
            asyncio.run(run(store, args))
    except (ValueError, RuntimeError, OSError, StopIteration) as error:
        raise SystemExit(
            str(error) or "設定またはキャラクターが見つかりません。"
        ) from error


if __name__ == "__main__":
    main()

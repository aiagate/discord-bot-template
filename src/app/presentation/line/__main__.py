import logging
import os
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from pprint import pformat

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from flow_med import Mediator
from flow_res import is_err
from injector import Injector
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    AsyncApiClient,
    AsyncMessagingApi,
    Configuration,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhook import WebhookParser
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.webhooks.models.user_source import UserSource

from app import container
from app.infrastructure.database import init_db
from app.usecases.chat.save_line_chat import SaveLineChatCommand

logging.basicConfig(
    level=logging.DEBUG,
    format=("%(message)s"),
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_environment() -> None:
    """Load environment variables from .env files."""
    # プロジェクトルートディレクトリを取得
    # app/presentation/line/__main__.py -> app/presentation/line/ -> app/presentation/ -> app/ -> src/ -> root
    root_dir = Path(__file__).parent.parent.parent.parent.parent

    # .env.local が存在すれば優先的に読み込む（開発環境用）
    env_local = root_dir / ".env.local"
    if env_local.exists():
        load_dotenv(env_local)
        return

    # .env ファイルを読み込む（本番環境用）
    env_file = root_dir / ".env"
    if env_file.exists():
        load_dotenv(env_file)


# 環境変数を読み込む
load_environment()

# シークレット/トークンを取得
channel_secret = os.getenv("LINE_CHANNEL_SECRET")
if channel_secret is None:
    logger.error("LINE_CHANNEL_SECRET  environment variable is not set")
    sys.exit(1)
channel_access_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
if channel_access_token is None:
    logger.error("LINE_CHANNEL_ACCESS_TOKEN  environment variable is not set")
    sys.exit(1)

configuration = Configuration(access_token=channel_access_token)
parser = WebhookParser(channel_secret)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    db_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./bot.db")
    init_db(db_url, echo=True)
    injector = Injector([container.configure])
    Mediator.initialize(injector)

    async_api_client = AsyncApiClient(configuration)
    app.state.line_bot_api = AsyncMessagingApi(async_api_client)
    yield


app = FastAPI(lifespan=lifespan)


@app.post("/callback")
async def handle_callback(request: Request):
    signature = request.headers["X-Line-Signature"]

    body = await request.body()
    body = body.decode()

    try:
        parsed = parser.parse(body, signature)
    except InvalidSignatureError as e:
        raise HTTPException(status_code=400, detail="Invalid signature") from e

    line_bot_api = request.app.state.line_bot_api

    events = parsed if isinstance(parsed, list) else (parsed.events or [])

    for event in events:
        logger.info(f"Received event: {event}")
        logger.info(f"{pformat(vars(event))}")

        match event:
            case MessageEvent():
                logger.info(f"Received message event: {event.message}")
                if isinstance(event.message, TextMessageContent):
                    logger.info(f"Received text message: {event.message}")

                    if isinstance(event.source, UserSource):
                        user_id = event.source.user_id

                        if user_id is None:
                            logger.warning("User ID is None in UserSource")
                            continue

                        save_result = await Mediator.send_async(
                            SaveLineChatCommand(
                                user_id=user_id,
                                content=event.message.text,
                            )
                        )

                        if is_err(save_result):
                            await line_bot_api.reply_message(
                                ReplyMessageRequest(
                                    replyToken=event.reply_token or "",
                                    messages=[
                                        TextMessage(
                                            text="メッセージの保存に失敗しました。",
                                            quickReply=None,
                                            quoteToken=None,
                                        )
                                    ],
                                    notificationDisabled=False,
                                )
                            )
                            return
                return "OK"
            case _:
                logger.info(f"Received non-message event: {event}")
                return "OK"

    return "OK"


def start() -> None:
    import uvicorn

    uvicorn.run("app.presentation.line.__main__:app", reload=True)


if __name__ == "__main__":
    start()

import logging
import os
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from injector import Injector

from app import container
from app.application.mediator import ApplicationMediator
from app.environment import load_environment
from app.infrastructure.database import init_db
from app.presentation.api.routers import teams, users

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Initialize application services on startup."""
    # 0. 環境変数の読み込み（プロセス環境 > .env.local > .env）
    #    uvicorn で直接モジュールを指定された場合も lifespan 内で確実に読み込む。
    load_environment()

    # 1. Initialize Database
    db_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./bot.db")
    init_db(db_url, echo=True)

    # 2. Initialize Dependency Injection & Mediator
    # We use the same container configuration as the Discord Bot
    injector = Injector([container.configure])
    app.state.mediator = injector.get(ApplicationMediator)

    logger.info("Application initialized successfully")

    yield

    # Shutdown logic if needed


app = FastAPI(title="Discord Bot API", lifespan=lifespan)

app.include_router(teams.router)
app.include_router(users.router)


def start() -> None:
    """Entry point for the FastAPI application."""
    import uvicorn

    uvicorn.run(
        "app.presentation.api.__main__:app", host="127.0.0.1", port=8000, reload=True
    )


if __name__ == "__main__":
    start()

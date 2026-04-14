import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from flow_med import Mediator
from injector import Injector

from app import container
from app.api.routers import teams, users
from app.infrastructure.database import init_db

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Initialize application services on startup."""
    # 1. Initialize Database
    db_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./bot.db")
    init_db(db_url, echo=True)

    # 2. Initialize Dependency Injection & Mediator
    # We use the same container configuration as the Discord Bot
    injector = Injector([container.configure])
    Mediator.initialize(injector)

    logger.info("Application initialized successfully")

    yield

    # Shutdown logic if needed


app = FastAPI(title="Discord Bot API", lifespan=lifespan)

app.include_router(teams.router)
app.include_router(users.router)


def start() -> None:
    """Entry point for the FastAPI application."""
    import uvicorn

    uvicorn.run("app.api.main:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    start()

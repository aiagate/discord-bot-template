import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from injector import Injector

from app import container
from app.api.routers import teams, users
from app.infrastructure.database import init_db
from app.mediator import Mediator

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize application services on startup."""
    # 1. Initialize Database
    db_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./bot.db")
    init_db(db_url, echo=True)

    # 2. Initialize Dependency Injection & Mediator
    # We use the same container configuration as the Discord Bot
    injector = Injector([container.configure])
    Mediator.initialize(injector)

    # 3. Initialize AI Agent
    from app.domain.interfaces.ai_service import IAIService

    ai_service = injector.get(IAIService)
    await ai_service.initialize_ai_agent()

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

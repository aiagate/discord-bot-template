"""Daily worker for asynchronous user-memory consolidation."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from flow_res import is_err
from injector import Injector

from app import container
from app.application.mediator import ApplicationMediator
from app.contracts.ports import IUserMemoryExtractor
from app.infrastructure.database import init_db
from app.usecases.memory.consolidate_user_memory import (
    ConsolidateUserMemoryCommand,
)

logger = logging.getLogger(__name__)
JST = ZoneInfo("Asia/Tokyo")
RUN_TIME = time(hour=3, tzinfo=JST)
PROJECT_ROOT = Path(__file__).resolve().parents[4]


def _load_environment() -> None:
    """Load the repository's local environment files."""
    for filename in (".env.local", ".env"):
        path = PROJECT_ROOT / filename
        if path.exists():
            load_dotenv(path, override=True)
            return


def _delay_until_next_run(now: datetime) -> float:
    """Return seconds until the next 03:00 JST run."""
    current = now.astimezone(JST)
    scheduled = datetime.combine(current.date(), RUN_TIME, tzinfo=JST)
    if current >= scheduled:
        scheduled += timedelta(days=1)
    return max(0.0, (scheduled - current).total_seconds())


async def _consolidate(mediator: ApplicationMediator) -> None:
    """Run one consolidation pass and log its bounded result."""
    result = await mediator.send_async(ConsolidateUserMemoryCommand())
    if is_err(result):
        logger.error("User memory consolidation failed: %s", result.error)
        return
    logger.info("User memory consolidation completed: %s", result.value)


async def main() -> None:
    """Start the daily worker, or execute one pass when requested."""
    _load_environment()
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        logger.error("GEMINI_API_KEY is required for the memory worker.")
        return

    from google import genai
    from google.genai import types

    from app.infrastructure.gemini.user_memory_extractor import (
        GeminiUserMemoryExtractor,
    )

    init_db(os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./bot.db"), echo=False)
    memory_extractor = GeminiUserMemoryExtractor(
        genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=120_000,
                retry_options=types.HttpRetryOptions(
                    attempts=3,
                    initial_delay=1.0,
                    max_delay=5.0,
                ),
            ),
        ),
        model=os.getenv("MEMORY_GEMINI_MODEL", "").strip()
        or os.getenv("GEMINI_MODEL", "").strip()
        or "gemini-3.8-flash",
    )
    worker_injector = Injector([container.configure])
    worker_injector.binder.bind(IUserMemoryExtractor, to=memory_extractor)
    mediator = worker_injector.get(ApplicationMediator)

    try:
        if os.getenv("WORKER_RUN_ONCE", "") == "1":
            await _consolidate(mediator)
            return
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()

        def stop() -> None:
            """Request a graceful worker shutdown."""
            stop_event.set()

        for signum in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(signum, stop)
            except NotImplementedError:
                pass

        while not stop_event.is_set():
            delay = _delay_until_next_run(datetime.now(JST))
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=delay)
            except TimeoutError:
                await _consolidate(mediator)
        logger.info("User memory worker stopped.")
    finally:
        await memory_extractor.aclose()


def start() -> None:
    """Synchronous console-script entry point."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    start()

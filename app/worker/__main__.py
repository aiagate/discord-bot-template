import asyncio
import logging
import os
import signal
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

from dotenv import load_dotenv
from flow_med import Mediator
from injector import Injector

from app import container
from app.domain.interfaces.event_bus import IEventBus
from app.infrastructure.database import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def load_environment() -> None:
    """Load environment variables from .env files."""
    root_dir = Path(__file__).parent.parent.parent
    env_local = root_dir / ".env.local"
    if env_local.exists():
        load_dotenv(env_local)
        return
    env_file = root_dir / ".env"
    if env_file.exists():
        load_dotenv(env_file)


async def _run_periodic_task(
    interval: int, func: Callable[[], Awaitable[None]]
) -> None:
    """Run a function periodically with the given interval."""
    while True:
        try:
            await func()
        except Exception as e:
            logger.error(f"Error in scheduled task {func.__name__}: {e}", exc_info=True)
        await asyncio.sleep(interval)


async def main() -> None:
    """Worker entry point."""
    logger.info("Starting Worker process...")

    # 0. 環境変数の読み込み
    load_environment()

    # 1. データベースとDIコンテナの初期化
    db_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./bot.db")
    init_db(db_url, echo=True)

    injector = Injector([container.configure])

    # Mediatorの初期化
    Mediator.initialize(injector)

    # 2. EventBusの取得
    event_bus = injector.get(IEventBus)

    # 3. ハンドラーと定期タスクの登録
    import app.worker.handlers as _  # type: ignore[reportUnusedImport] # noqa: F401
    from app.worker.registry import registry

    # イベントハンドラーの登録
    for topic, handler in registry.registered_handlers:
        await event_bus.subscribe(topic, handler)
        logger.info(f"Registered event handler for topic: {topic}")

    # 定期実行タスクの起動
    for interval, task_func in registry.scheduled_tasks:
        asyncio.create_task(_run_periodic_task(interval, task_func))
        logger.info(
            f"Started scheduled task: {task_func.__name__} (interval: {interval}s)"
        )

    logger.info("Worker process initialized and listening for events.")

    # 4. 停止信号の処理

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def handle_stop_signal() -> None:
        logger.info("Stop signal received.")
        stop_event.set()

    # Windows環境等での互換性を考慮したシグナルハンドリング
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handle_stop_signal)
        except NotImplementedError:
            # add_signal_handler がサポートされていない環境（Windows等）
            pass

    # 5. イベントバスの起動
    await event_bus.start()

    try:
        # 停止信号を待機
        await stop_event.wait()
    except asyncio.CancelledError:
        pass
    finally:
        logger.info("Shutting down Worker process...")
        await event_bus.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

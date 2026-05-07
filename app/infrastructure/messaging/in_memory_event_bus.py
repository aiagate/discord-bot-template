import asyncio
import logging
from typing import Any

from app.domain.interfaces.event_bus import EventHandler, IEventBus

logger = logging.getLogger(__name__)


class InMemoryEventBus(IEventBus):
    """同一プロセス内でのみ動作するインメモリ・イベントバスの実装。

    開発、テスト、および小規模な単一プロセス運用に使用します。
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = {}
        self._queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
        self._running = False
        self._task: asyncio.Task[None] | None = None

    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        """キューにメッセージを追加します。"""
        await self._queue.put((topic, payload))
        logger.debug(f"Published to {topic}: {payload}")

    async def subscribe(self, topic: str, handler: EventHandler) -> None:
        """ハンドラーを登録します。"""
        if topic not in self._handlers:
            self._handlers[topic] = []
        self._handlers[topic].append(handler)
        logger.debug(f"Subscribed to {topic}")

    async def start(self) -> None:
        """バックグラウンドでキューを監視して処理を開始します。"""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._worker_loop())
        logger.info("InMemoryEventBus started")

    async def stop(self) -> None:
        """処理を停止します。"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("InMemoryEventBus stopped")

    async def _worker_loop(self) -> None:
        """キューを監視し、受信したメッセージをハンドラーにディスパッチします。"""
        while self._running:
            try:
                topic, payload = await self._queue.get()

                handlers = self._handlers.get(topic, [])
                if not handlers:
                    logger.warning(f"No handlers registered for topic: {topic}")

                # 同一トピックのハンドラーを並列実行
                await asyncio.gather(
                    *[handler(payload) for handler in handlers], return_exceptions=True
                )

                self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    f"Error in InMemoryEventBus worker loop: {e}", exc_info=True
                )
                await asyncio.sleep(1)  # エラー時は少し待機

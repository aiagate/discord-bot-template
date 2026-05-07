from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any

# ハンドラー関数の型定義: payload(dict) を受け取り、None を返す非同期関数
EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class IEventBus(ABC):
    """イベントバスの抽象インターフェース。

    API、Bot、Worker間での非同期メッセージングを抽象化します。
    """

    @abstractmethod
    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        """指定したトピックにイベントを発行します。"""
        pass

    @abstractmethod
    async def subscribe(self, topic: str, handler: EventHandler) -> None:
        """指定したトピックのイベントを購読します。"""
        pass

    @abstractmethod
    async def start(self) -> None:
        """イベントバスのリスニングを開始します（Workerプロセス等で使用）。"""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """イベントバスを停止します。"""
        pass

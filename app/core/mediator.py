import logging
from abc import ABC, ABCMeta, abstractmethod
from typing import Any, ClassVar

from injector import Injector

from app.core.result import Result, ResultAwaitable

logger = logging.getLogger(__name__)


class AutoRegisterMeta(type):
    def __new__(
        mcs,
        name: str,
        bases: tuple[type, ...],
        class_dict: dict[str, Any],
    ) -> type:
        cls = super().__new__(mcs, name, bases, class_dict)

        if name == "RequestHandler":
            return cls

        # RequestHandler の自動登録
        if "handle" in class_dict and not hasattr(cls, "__abstractmethods__"):
            # Request の型を取得
            request_type = cls.__orig_bases__[0].__args__[0]  # type: ignore[attr-defined]
            logger.debug(
                "AutoRegisterMeta: %s -> %s",
                request_type,  # type: ignore[arg-type]
                cls,
            )
            # Mediator に登録
            Mediator.register(request_type, cls)  # type: ignore[arg-type]

        return cls


class CombinedMeta(ABCMeta, AutoRegisterMeta):
    pass


class Request[R]:
    pass


class RequestHandler[T, R](ABC, metaclass=CombinedMeta):
    @abstractmethod
    async def handle(self, request: T) -> R:
        pass


class Mediator:
    _request_handlers: ClassVar[dict[type[Any], type[Any]]] = {}
    _injector: ClassVar[Injector | None] = None

    @classmethod
    def initialize(cls, injector: Injector) -> None:
        """Initialize mediator with injector.

        This method should be called once at application startup,
        before sending any requests.
        """
        cls._injector = injector

    @classmethod
    def send_async[T, E: Exception](
        cls, request: Request[Result[T, E]]
    ) -> ResultAwaitable[T, E]:
        """
        Send a request to its handler.

        Returns ResultAwaitable for method chaining.

        Args:
            request: The request to handle

        Returns:
            ResultAwaitable wrapping the handler result
        """

        async def execute() -> Result[T, E]:
            logger.debug("Mediator.send_async: %s", request)
            if cls._injector is None:
                raise RuntimeError(
                    "Mediator not initialized. Call Mediator.initialize() first."
                )
            handler_provider = cls._request_handlers.get(type(request))
            if not handler_provider:
                raise HandlerNotFoundError(request)

            handler = cls._injector.get(handler_provider)
            return await handler.handle(request)

        return ResultAwaitable(execute())

    @classmethod
    def register(cls, request_type: type[Any], handler_type: type[Any]) -> None:
        logger.debug("Mediator.register: %s -> %s", request_type, handler_type)
        cls._request_handlers[request_type] = handler_type


class MediatorError(Exception):
    pass


class HandlerNotFoundError(MediatorError):
    def __init__(self, target: Any) -> None:
        super().__init__(
            f"Handler not found for request type: {type(target)}",
        )


__all__ = [
    "HandlerNotFoundError",
    "Mediator",
    "RequestHandler",
]

"""Application port for Times post delivery."""

from abc import ABC, abstractmethod

from flow_res import Result

from app.contracts.messages.times_message import TimesEpisodePlan
from app.contracts.ports.speech_publisher import SpeechPublishError


class ITimesPublisher(ABC):
    """Deliver Times episode posts through the single Times webhook."""

    @abstractmethod
    async def deliver(self, plan: TimesEpisodePlan) -> Result[None, SpeechPublishError]:
        """Deliver posts in the plan sequentially and record progress."""
        pass

    @abstractmethod
    async def recover_pending(self) -> None:
        """Recover interrupted deliveries at startup."""
        pass

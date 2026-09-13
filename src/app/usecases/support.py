"""Advance support and communicate results through independent boundaries."""

import asyncio
import logging
import time
from collections.abc import Callable
from contextlib import suppress

from app.contracts.messages.support import Notice, Outcome, RuntimeObservation
from app.contracts.ports.support import Publisher, Speaker, SupportStore, Thinker

logger = logging.getLogger(__name__)


class SupportRunner:
    """Run one due activity, honoring newer input and a bounded execution time."""

    def __init__(
        self,
        store: SupportStore,
        thinker: Thinker,
        *,
        timeout: float = 1200,
        clock: Callable[[], float] = time.time,
        check_interval: float = 1,
    ) -> None:
        self.store = store
        self.thinker = thinker
        self.timeout = timeout
        self.clock = clock
        self.check_interval = check_interval

    async def tick(self) -> bool:
        """Run due support even when no human has sent a new message (U2–U6)."""
        activity = self.store.claim(self.clock())
        if activity is None:
            return False
        work: asyncio.Task[Outcome] | None = None
        try:
            context = self.store.context(activity, self.clock())

            async def record(kind: str, content: str) -> None:
                self.store.record(activity, kind, content, self.clock())

            work = asyncio.create_task(self.thinker.run(context, record))
            async with asyncio.timeout(self.timeout):
                while not work.done():
                    await asyncio.wait({work}, timeout=self.check_interval)
                    current = self.store.current(activity.id)
                    if current.revision != activity.revision:
                        self.store.record(
                            activity,
                            "superseded",
                            "新しい入力または停止で中断。",
                            self.clock(),
                        )
                        return True
                outcome = await work
            self.store.finish(activity, outcome, self.clock())
        except asyncio.CancelledError:
            self.store.fail(
                activity, "実行が中断された。外部操作の結果を確認する。", self.clock()
            )
            raise
        except Exception as error:
            logger.exception("Support attempt failed: %s", activity.id)
            self.store.fail(
                activity,
                f"実行失敗 ({type(error).__name__})。結果を確認する。",
                self.clock(),
            )
        finally:
            if work is not None and not work.done():
                work.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await work
        return True


class Communicator:
    """Deliver saved results without making work depend on expression (U7)."""

    def __init__(
        self, store: SupportStore, publisher: Publisher, speaker: Speaker | None = None
    ) -> None:
        self.store = store
        self.publisher = publisher
        self.speaker = speaker

    async def flush(self) -> int:
        """Retry delivery of immutable notices without rerunning their work."""
        count = 0
        for notice in self.store.pending_notices():
            character = self.store.character(notice.character_id)
            if notice.rendered is None:
                content = notice.content
                if self.speaker is not None:
                    try:
                        async with asyncio.timeout(30):
                            rendered = (
                                await self.speaker.render(notice, character)
                            ).strip()
                            if rendered:
                                content = rendered
                                self.store.observe(
                                    RuntimeObservation(
                                        component="expression",
                                        status="success",
                                        observed_at=time.time(),
                                        source=f"notice:{notice.id}",
                                    )
                                )
                            else:
                                raise ValueError("表現結果が空です。")
                    except Exception:
                        logger.warning(
                            "Expression failed; using saved content", exc_info=True
                        )
                        self.store.observe(
                            RuntimeObservation(
                                component="expression",
                                status="failure",
                                observed_at=time.time(),
                                source=f"notice:{notice.id}",
                            )
                        )
                self.store.save_rendered(notice.id, content)
                notice = Notice.model_validate(
                    {**notice.model_dump(), "rendered": content}
                )
            try:
                async with asyncio.timeout(30):
                    receipt = await self.publisher.send(notice, character)
            except Exception:
                logger.warning("Delivery pending: %s", notice.id, exc_info=True)
                self.store.observe(
                    RuntimeObservation(
                        component="delivery",
                        status="failure",
                        observed_at=time.time(),
                        source=f"notice:{notice.id}",
                    )
                )
                continue
            self.store.delivered(notice.id, receipt)
            count += 1
        return count

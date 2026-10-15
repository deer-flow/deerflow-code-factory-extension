"""Single-process periodic Issue discovery."""

import asyncio
import logging

from .poller import Poller
from .store import FactoryStore

logger = logging.getLogger(__name__)


class PollService:
    def __init__(
        self, store: FactoryStore, poller: Poller, interval_seconds: int = 180
    ):
        if interval_seconds < 30:
            raise ValueError("poll_interval_seconds must be at least 30")
        self.store = store
        self.poller = poller
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task | None = None

    async def start(self, deps) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while True:
            for factory in self.store.list_enabled_factories():
                try:
                    await self.poller.scan_factory(factory["id"])
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "Code factory Issue scan failed for factory %s", factory["id"]
                    )
            await asyncio.sleep(self.interval_seconds)

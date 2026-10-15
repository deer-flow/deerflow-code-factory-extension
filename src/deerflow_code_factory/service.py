"""Single-process periodic Issue discovery."""

import asyncio
import logging

from .poller import Poller
from .store import FactoryStore
from .github.completion import GitHubCompletion
from .github.gh_cli import GhClient

logger = logging.getLogger(__name__)


class PollService:
    def __init__(
        self,
        store: FactoryStore,
        poller: Poller,
        interval_seconds: int = 180,
        *,
        supervisor=None,
        gh=None,
    ):
        if interval_seconds < 30:
            raise ValueError("poll_interval_seconds must be at least 30")
        self.store = store
        self.poller = poller
        self.interval_seconds = interval_seconds
        self.supervisor = supervisor
        self.completion = GitHubCompletion(gh or GhClient())
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
        if self.supervisor is not None:
            await self.supervisor.stop()

    async def _refresh_job(self, factory, job) -> None:
        events = self.store.list_events(job["id"])
        delivery = next(
            (
                event["evidence"]
                for event in reversed(events)
                if "pr_number" in event["evidence"]
            ),
            None,
        )
        if delivery is None:
            return
        result = await self.completion.refresh(
            factory,
            issue_number=job["issue_number"],
            pr_number=delivery["pr_number"],
            head_sha=delivery["head_sha"],
        )
        phase = result["state"]
        if (
            phase in {"done", "awaiting_merge", "failed_checks", "stale_head", "closed"}
            and phase != job["phase"]
        ):
            self.store.transition(
                job["id"],
                expected_version=job["version"],
                phase=phase,
                evidence={**delivery, **result},
            )

    async def _loop(self) -> None:
        while True:
            for factory in self.store.list_enabled_factories():
                try:
                    await self.poller.scan_factory(factory["id"])
                    for job in self.store.list_jobs(factory["id"]):
                        if job["phase"] in {"awaiting_checks", "awaiting_merge"}:
                            await self._refresh_job(factory, job)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "Code factory Issue scan failed for factory %s", factory["id"]
                    )
            await asyncio.sleep(self.interval_seconds)

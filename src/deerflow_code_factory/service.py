"""Single-process periodic Issue discovery."""

import asyncio
import logging

from .poller import Poller
from .store import FactoryStore
from .github.completion import GitHubCompletion
from .github.gh_cli import GhClient
from .review_repair import ReviewRepair

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
        required_checks: tuple[str, ...] = (),
        approver_logins: tuple[str, ...] = (),
        automation_login: str | None = None,
    ):
        if interval_seconds < 30:
            raise ValueError("poll_interval_seconds must be at least 30")
        self.store = store
        self.poller = poller
        self.interval_seconds = interval_seconds
        self.supervisor = supervisor
        client = gh or GhClient()
        self.completion = GitHubCompletion(
            client,
            required_checks=required_checks,
            approver_logins=approver_logins,
            automation_login=automation_login,
        )
        self.review_repair = (
            ReviewRepair(store, client, supervisor.workspace_root, supervisor.checker)
            if supervisor is not None
            else None
        )
        self._task: asyncio.Task | None = None

    async def start(self, deps) -> None:
        if self._task is not None:
            return
        if self.review_repair is not None:
            self.review_repair.set_invoker(getattr(deps, "model_invoker", None))
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
        if self.review_repair is not None:
            await self.review_repair.stop()

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
        prior_merge_attempt = any(
            event["evidence"].get("merge_attempt") for event in events
        )
        result = await self.completion.refresh(
            factory,
            issue_number=job["issue_number"],
            pr_number=delivery["pr_number"],
            head_sha=delivery["head_sha"],
            prior_merge_attempt=prior_merge_attempt,
        )
        phase = result["state"]
        if job["phase"] == "review_blocked" and phase == "awaiting_review":
            attempted = {
                identifier
                for event in events
                for identifier in (
                    event["evidence"].get("addressed_feedback_ids", [])
                    + event["evidence"].get("attempted_feedback_ids", [])
                )
            }
            if not any(
                item["id"] not in attempted for item in result.get("feedback", [])
            ):
                return
        if job["phase"] == "addressing_review" and phase not in {
            "done",
            "merged_manual",
            "merged_unknown",
            "closed",
        }:
            return
        if phase == "awaiting_merge" and result.get("ready"):
            if not prior_merge_attempt:
                job = self.store.transition(
                    job["id"],
                    expected_version=job["version"],
                    phase="awaiting_merge",
                    evidence={
                        **delivery,
                        "merge_attempt": True,
                        "head_sha": delivery["head_sha"],
                    },
                )
            result = await self.completion.merge_if_ready(
                factory,
                issue_number=job["issue_number"],
                pr_number=delivery["pr_number"],
                head_sha=delivery["head_sha"],
            )
            phase = result["state"]
        if phase in {
            "done",
            "merged_manual",
            "merged_unknown",
            "awaiting_checks",
            "awaiting_review",
            "review_blocked",
            "awaiting_approval",
            "awaiting_merge",
            "failed_checks",
            "stale_head",
            "closed",
        } and (
            phase != job["phase"]
            or result.get("reason")
            != (events[-1]["evidence"].get("reason") if events else None)
        ):
            job = self.store.transition(
                job["id"],
                expected_version=job["version"],
                phase=phase,
                evidence={**delivery, **result},
            )
        if phase == "awaiting_review" and self.review_repair is not None:
            attempted = {
                identifier
                for event in self.store.list_events(job["id"])
                for identifier in (
                    event["evidence"].get("addressed_feedback_ids", [])
                    + event["evidence"].get("attempted_feedback_ids", [])
                )
            }
            feedback = [
                item
                for item in result.get("feedback", [])
                if item["id"] not in attempted
            ]
            if feedback:
                spec = next(
                    (
                        event["evidence"]["spec"]
                        for event in events
                        if "spec" in event["evidence"]
                    ),
                    "",
                )
                started = self.review_repair.start(
                    job, factory, delivery, feedback, spec
                )
                if not started and self.review_repair.invoker is None:
                    self.store.transition(
                        job["id"],
                        expected_version=job["version"],
                        phase="review_blocked",
                        evidence={
                            **delivery,
                            "reason": "background model invocation grant is unavailable",
                        },
                    )

    async def _loop(self) -> None:
        while True:
            for factory in self.store.list_enabled_factories():
                try:
                    await self.poller.scan_factory(factory["id"])
                    for job in self.store.list_jobs(factory["id"]):
                        if job["phase"] in {
                            "awaiting_checks",
                            "awaiting_review",
                            "awaiting_approval",
                            "addressing_review",
                            "review_blocked",
                            "awaiting_merge",
                            "failed_checks",
                            "stale_head",
                        }:
                            await self._refresh_job(factory, job)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "Code factory Issue scan failed for factory %s", factory["id"]
                    )
            await asyncio.sleep(self.interval_seconds)

"""One-process supervised development jobs, launched from an authenticated action."""

import asyncio
import logging

from .github.context import load_repository_context
from .github.delivery import GitHubDelivery
from .github.gh_cli import GhClient, GhIssueSource
from .requirements import IssueRef
from .stages import AgentStages
from .store import FactoryStore

logger = logging.getLogger(__name__)


class JobSupervisor:
    def __init__(self, store: FactoryStore, gh: GhClient | None = None):
        self.store = store
        self.gh = gh or GhClient()
        self._tasks: dict[str, asyncio.Task] = {}

    def start(self, job_id: str, runs) -> bool:
        if runs is None:
            raise RuntimeError("host AgentRuns capability unavailable")
        job = self.store.get_job_internal(job_id)
        if job is None:
            raise KeyError(job_id)
        if job["phase"] not in {"draft", "blocked", "failed"}:
            raise ValueError("job has already started")
        active = self._tasks.get(job_id)
        if active is not None and not active.done():
            return False
        task = asyncio.create_task(self._run(job_id, runs))
        self._tasks[job_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(job_id, None))
        return True

    async def stop(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    def _phase(self, job_id: str, phase: str, evidence: dict) -> None:
        job = self.store.get_job_internal(job_id)
        if job is None:
            raise KeyError(job_id)
        self.store.transition(
            job_id, expected_version=job["version"], phase=phase, evidence=evidence
        )

    async def _run(self, job_id: str, runs) -> None:
        try:
            job = self.store.get_job_internal(job_id)
            factory = self.store.get_factory(job["factory_id"])
            if not factory or not factory["enabled"]:
                raise ValueError("factory disabled")
            source = GhIssueSource(self.gh)
            ticket = await source.fetch(
                factory, IssueRef(job["issue_id"], job["issue_number"])
            )
            if (
                ticket.state != "open"
                or "factory:ready" not in ticket.labels
                or ticket.is_pull_request
            ):
                raise ValueError("issue is no longer ready")
            root = f"repos/{factory['owner']}/{factory['repo']}"
            repo = await self.gh.api(root)
            if repo["id"] != factory["repository_id"] or not repo.get("default_branch"):
                raise ValueError("repository identity or default branch changed")
            branch = repo["default_branch"]
            stages = AgentStages(runs)
            self._phase(
                job_id, "planning", {"issue_updated_at": ticket.updated_at.isoformat()}
            )
            tree = await load_repository_context(self.gh, factory, branch)
            spec = await stages.plan(ticket.title, ticket.body, tree, ticket.comments)
            if not spec["ready"]:
                question = spec["question"][:1000]
                await self.gh.api(
                    f"{root}/issues/{ticket.number}/comments",
                    method="POST",
                    body={"body": f"代码工厂需要补充信息：{question}"},
                )
                self._phase(job_id, "blocked", {"question": question})
                return
            self._phase(job_id, "coding", {"spec": spec["spec"][:12000]})
            context = await load_repository_context(
                self.gh, factory, branch, spec.get("relevant_paths", [])
            )
            findings = []
            for attempt in range(1, 4):
                code = await stages.code(spec["spec"], context, findings)
                review = await stages.review(spec["spec"], code["files"])
                self._phase(
                    job_id,
                    "reviewing",
                    {
                        "attempt": attempt,
                        "approved": review["approved"],
                        "findings": review["findings"][:20],
                    },
                )
                if review["approved"]:
                    break
                findings = review["findings"]
            else:
                raise ValueError("independent review failed after three attempts")
            fresh = await source.fetch(
                factory, IssueRef(job["issue_id"], job["issue_number"])
            )
            if (
                fresh.updated_at != ticket.updated_at
                or "factory:ready" not in fresh.labels
            ):
                raise ValueError("Issue changed during development; re-plan required")
            delivered = await GitHubDelivery(self.gh).deliver(
                factory,
                issue_number=ticket.number,
                base_branch=branch,
                files=code["files"],
                title=ticket.title,
                description=f"Closes #{ticket.number}\n\nSpecification:\n{spec['spec'][:8000]}\n\nIndependent review: passed.",
            )
            self._phase(job_id, "awaiting_checks", delivered)
            try:
                await self.gh.api(
                    f"{root}/issues/{ticket.number}/comments",
                    method="POST",
                    body={
                        "body": f"代码工厂已提交 PR：{delivered['pr_url']}。等待仓库 CI 与合并规则验证。"
                    },
                )
            except Exception:
                logger.exception("Could not post PR progress for job %s", job_id)
        except asyncio.CancelledError:
            self._phase(job_id, "failed", {"reason": "cancelled"})
            raise
        except Exception as exc:
            logger.exception("Code factory job %s failed", job_id)
            self._phase(job_id, "failed", {"reason": str(exc)[:500]})

"""One-process supervised development jobs, launched from an authenticated action."""

import asyncio
import logging

from .checks import DockerChecker
from .github.delivery import GitHubDelivery
from .github.gh_cli import GhClient, GhIssueSource
from .requirements import IssueRef
from .stages import AgentStages
from .store import FactoryStore
from .workspace import JobWorkspace

logger = logging.getLogger(__name__)


class JobSupervisor:
    def __init__(
        self,
        store: FactoryStore,
        gh: GhClient | None = None,
        *,
        workspace_root: str | None = None,
        check_image: str = "python:3.12-slim",
        check_command: str = "python -m unittest discover -s tests",
    ):
        self.store = store
        self.gh = gh or GhClient()
        self.workspace_root = workspace_root or str(store.path.parent / "workspaces")
        self.checker = DockerChecker(check_image, check_command)
        self._tasks: dict[str, asyncio.Task] = {}

    def start(self, job_id: str, runs) -> bool:
        if runs is None:
            raise RuntimeError("host AgentRuns capability unavailable")
        job = self.store.get_job_internal(job_id)
        if job is None:
            raise KeyError(job_id)
        active = self._tasks.get(job_id)
        if active is not None and not active.done():
            return False
        if job["phase"] not in {"draft", "blocked", "failed"}:
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
            await asyncio.to_thread(self.checker.require_ready)
            root = f"repos/{factory['owner']}/{factory['repo']}"
            repo = await self.gh.api(root)
            if repo["id"] != factory["repository_id"] or not repo.get("default_branch"):
                raise ValueError("repository identity or default branch changed")
            branch = repo["default_branch"]
            base_ref = await self.gh.api(f"{root}/git/ref/heads/{branch}")
            base_sha = base_ref["object"]["sha"]
            workspace = JobWorkspace(self.workspace_root, job_id, job["version"])
            await asyncio.to_thread(
                workspace.prepare,
                factory["owner"],
                factory["repo"],
                base_sha,
                ticket.number,
            )
            stages = AgentStages(runs)
            self._phase(
                job_id,
                "planning",
                {
                    "issue_updated_at": ticket.updated_at.isoformat(),
                    "base_sha": base_sha,
                },
            )
            tree = await asyncio.to_thread(workspace.context)
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
            findings = []
            for attempt in range(1, 4):
                context = await asyncio.to_thread(
                    workspace.context, spec.get("relevant_paths") or None
                )
                code = await stages.code(spec["spec"], context, findings)
                await asyncio.to_thread(workspace.apply_files, code["files"])
                self._phase(job_id, "testing", {"attempt": attempt})
                checks = await asyncio.to_thread(self.checker.run, workspace.path)
                if not checks.passed:
                    findings = [
                        f"Local tests failed (exit {checks.exit_code}):\n{checks.output[:12000]}"
                    ]
                    self._phase(
                        job_id,
                        "coding",
                        {
                            "attempt": attempt,
                            "test_exit_code": checks.exit_code,
                            "test_output": checks.output[:12000],
                        },
                    )
                    continue
                diff = await asyncio.to_thread(workspace.diff)
                review = await stages.review(
                    spec["spec"],
                    code["files"],
                    f"git diff:\n{diff[:40000]}\nLocal tests passed:\n{checks.output[:10000]}",
                )
                self._phase(
                    job_id,
                    "reviewing",
                    {
                        "attempt": attempt,
                        "approved": review["approved"],
                        "findings": review["findings"][:20],
                        "test_exit_code": checks.exit_code,
                        "test_output": checks.output[:12000],
                    },
                )
                if review["approved"]:
                    break
                findings = review["findings"]
                self._phase(
                    job_id, "coding", {"attempt": attempt, "findings": findings[:20]}
                )
            else:
                raise ValueError(
                    "local tests or independent review failed after three attempts"
                )
            fresh = await source.fetch(
                factory, IssueRef(job["issue_id"], job["issue_number"])
            )
            if (
                fresh.updated_at != ticket.updated_at
                or "factory:ready" not in fresh.labels
            ):
                raise ValueError("Issue changed during development; re-plan required")
            latest_base = await self.gh.api(f"{root}/git/ref/heads/{branch}")
            if latest_base["object"]["sha"] != base_sha:
                raise ValueError(
                    "default branch changed during development; re-plan required"
                )
            head_sha = await asyncio.to_thread(workspace.commit_and_push, ticket.number)
            delivered = await GitHubDelivery(self.gh).create_pull_request_for_branch(
                factory,
                issue_number=ticket.number,
                head_branch=workspace.branch,
                base_branch=branch,
                head_sha=head_sha,
                base_sha=base_sha,
                title=ticket.title,
                description=(
                    f"Closes #{ticket.number}\n\nSpecification:\n{spec['spec'][:8000]}\n\n"
                    f"Changed files: {', '.join(item['path'] for item in code['files'])[:2000]}\n\n"
                    f"Local test command: `{self.checker.command}`\nLocal tests: passed.\n"
                    "Independent review: passed."
                ),
            )
            self._phase(job_id, "awaiting_checks", delivered)
            try:
                await GitHubDelivery(self.gh).post_review_summary(
                    factory,
                    delivered["pr_number"],
                    head_sha,
                    f"Local tests passed:\n```\n{checks.output[:3000]}\n```\nIndependent review: passed (attempt {attempt}).",
                )
            except Exception:
                logger.exception("Could not post review summary for job %s", job_id)
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

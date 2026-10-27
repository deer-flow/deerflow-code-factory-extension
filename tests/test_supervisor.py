import asyncio
from datetime import datetime, timezone

import pytest

from deerflow_code_factory.requirements import RequirementSnapshot
from deerflow_code_factory.store import FactoryStore
from deerflow_code_factory.supervisor import JobSupervisor


@pytest.mark.asyncio
async def test_start_is_idempotent_while_job_is_running(tmp_path, monkeypatch):
    store = FactoryStore(tmp_path / "factory.sqlite")
    factory = store.create_factory(
        owner_user_id="alice", repository_id=42, owner="acme", repo="widget"
    )
    job = store.create_or_get_job(factory["id"], issue_id=70, issue_number=7)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def run(self, job_id, runs):
        entered.set()
        await release.wait()

    monkeypatch.setattr(JobSupervisor, "_run", run)
    supervisor = JobSupervisor(store)
    assert supervisor.start(job["id"], object()) is True
    await entered.wait()
    store.transition(job["id"], expected_version=0, phase="planning", evidence={})
    assert supervisor.start(job["id"], object()) is False
    release.set()
    await supervisor.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("check_passes", [True, False])
async def test_explicit_job_start_runs_plan_code_review_and_pr(
    tmp_path, monkeypatch, check_passes
):
    store = FactoryStore(tmp_path / "factory.sqlite")
    factory = store.create_factory(
        owner_user_id="alice", repository_id=42, owner="acme", repo="widget"
    )
    store.set_factory_enabled(factory["id"], owner_user_id="alice", enabled=True)
    job = store.create_or_get_job(factory["id"], issue_id=70, issue_number=7)
    ticket = RequirementSnapshot(
        70,
        7,
        "Export",
        "Acceptance Criteria: CSV",
        3,
        "open",
        frozenset({"factory:ready"}),
        datetime(2026, 10, 15, tzinfo=timezone.utc),
    )

    async def fetch(self, factory, ref):
        return ticket

    async def context(*args, **kwargs):
        return "repo files"

    workspace_calls = []

    class Workspace:
        def __init__(self, root, job_id, version):
            self.path = tmp_path / "checkout"
            self.branch = f"code-factory/issue-7-run-{version}"

        def prepare(self, owner, repo, base_sha, issue_number):
            workspace_calls.append("clone")

        def context(self, paths=None):
            return "repository files and content"

        def apply_files(self, files):
            workspace_calls.append("apply")

        def diff(self):
            return "+def export(): pass"

        def commit_and_push(self, issue_number):
            workspace_calls.append("push")
            return "head1"

    class Checker:
        def __init__(self, *args):
            self.command = "python -m unittest discover -s tests"

        def require_ready(self):
            workspace_calls.append("preflight")

        def run(self, path):
            workspace_calls.append("test")
            return type(
                "Result",
                (),
                {
                    "passed": check_passes,
                    "exit_code": 0 if check_passes else 1,
                    "output": "1 test passed" if check_passes else "1 test failed",
                },
            )()

    class Stages:
        def __init__(self, runs):
            pass

        async def plan(self, *args):
            return {"ready": True, "spec": "CSV export", "relevant_paths": []}

        async def code(self, *args):
            return {"files": [{"path": "export.py", "content": "pass\n"}]}

        async def review(self, *args):
            return {"approved": True, "findings": []}

    class Delivery:
        def __init__(self, gh):
            pass

        async def create_pull_request_for_branch(self, *args, **kwargs):
            workspace_calls.append("pr")
            return {
                "pr_number": 9,
                "pr_url": "https://github.com/acme/widget/pull/9",
                "head_branch": "code-factory/issue-7-run-0",
                "head_sha": "head1",
            }

        async def post_review_summary(self, *args):
            workspace_calls.append("summary")

    class Gh:
        async def api(self, path, *, method="GET", body=None):
            if path == "repos/acme/widget":
                return {"id": 42, "default_branch": "main"}
            if path == "repos/acme/widget/git/ref/heads/main":
                return {"object": {"sha": "a" * 40}}
            if path.endswith("/comments"):
                return {"id": 1}
            raise AssertionError(path)

    monkeypatch.setattr("deerflow_code_factory.supervisor.GhIssueSource.fetch", fetch)
    monkeypatch.setattr("deerflow_code_factory.supervisor.JobWorkspace", Workspace)
    monkeypatch.setattr("deerflow_code_factory.supervisor.DockerChecker", Checker)
    monkeypatch.setattr("deerflow_code_factory.supervisor.AgentStages", Stages)
    monkeypatch.setattr("deerflow_code_factory.supervisor.GitHubDelivery", Delivery)
    supervisor = JobSupervisor(store, Gh())
    assert supervisor.start(job["id"], object())
    expected_phase = "awaiting_checks" if check_passes else "failed"
    for _ in range(100):
        if store.get_job_internal(job["id"])["phase"] == expected_phase:
            break
        await asyncio.sleep(0.01)
    assert store.get_job_internal(job["id"])["phase"] == expected_phase
    if check_passes:
        assert store.list_events(job["id"])[-1]["evidence"]["head_sha"] == "head1"
        assert workspace_calls == [
            "preflight",
            "clone",
            "apply",
            "test",
            "push",
            "pr",
            "summary",
        ]
    else:
        assert "push" not in workspace_calls and "pr" not in workspace_calls
        assert workspace_calls.count("test") == 3
    await supervisor.stop()

import asyncio
from datetime import datetime, timezone

import pytest

from deerflow_code_factory.requirements import RequirementSnapshot
from deerflow_code_factory.store import FactoryStore
from deerflow_code_factory.supervisor import JobSupervisor


@pytest.mark.asyncio
async def test_explicit_job_start_runs_plan_code_review_and_pr(tmp_path, monkeypatch):
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

        async def deliver(self, *args, **kwargs):
            return {
                "pr_number": 9,
                "pr_url": "https://github.com/acme/widget/pull/9",
                "head_sha": "head1",
            }

    class Gh:
        async def api(self, path, *, method="GET", body=None):
            if path == "repos/acme/widget":
                return {"id": 42, "default_branch": "main"}
            if path.endswith("/comments"):
                return {"id": 1}
            raise AssertionError(path)

    monkeypatch.setattr("deerflow_code_factory.supervisor.GhIssueSource.fetch", fetch)
    monkeypatch.setattr(
        "deerflow_code_factory.supervisor.load_repository_context", context
    )
    monkeypatch.setattr("deerflow_code_factory.supervisor.AgentStages", Stages)
    monkeypatch.setattr("deerflow_code_factory.supervisor.GitHubDelivery", Delivery)
    supervisor = JobSupervisor(store, Gh())
    assert supervisor.start(job["id"], object())
    for _ in range(100):
        if store.get_job_internal(job["id"])["phase"] == "awaiting_checks":
            break
        await asyncio.sleep(0)
    assert store.get_job_internal(job["id"])["phase"] == "awaiting_checks"
    assert store.list_events(job["id"])[-1]["evidence"]["head_sha"] == "head1"
    await supervisor.stop()

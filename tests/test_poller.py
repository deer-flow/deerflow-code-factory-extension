from datetime import datetime, timezone
from pathlib import Path

import pytest

from deerflow_code_factory.poller import Poller
from deerflow_code_factory.requirements import IssueRef, RequirementSnapshot
from deerflow_code_factory.store import FactoryStore


class FakeIssues:
    def __init__(
        self, issues: list[RequirementSnapshot], *, fail_at: int | None = None
    ):
        self.issues = issues
        self.fail_at = fail_at
        self.fetches: list[int] = []

    async def list_candidates(self, factory, since):
        return [IssueRef(issue_id=i.issue_id, number=i.number) for i in self.issues]

    async def fetch(self, factory, ref):
        self.fetches.append(ref.issue_id)
        if self.fail_at == ref.issue_id:
            raise OSError("GitHub unavailable")
        return next(i for i in self.issues if i.issue_id == ref.issue_id)


def issue(issue_id: int, *, pull_request: bool = False) -> RequirementSnapshot:
    return RequirementSnapshot(
        issue_id=issue_id,
        number=issue_id,
        title="Add export",
        body="Export records",
        author_id=5,
        state="open",
        labels=frozenset({"factory:ready"}),
        updated_at=datetime(2026, 10, 15, 1, issue_id, tzinfo=timezone.utc),
        is_pull_request=pull_request,
    )


@pytest.mark.asyncio
async def test_scan_deduplicates_issues_and_ignores_pull_requests(
    tmp_path: Path,
) -> None:
    store = FactoryStore(tmp_path / "factory.sqlite")
    factory = store.create_factory(
        owner_user_id="alice", repository_id=42, owner="acme", repo="widget"
    )
    source = FakeIssues([issue(1), issue(2, pull_request=True)])
    poller = Poller(store, source)
    assert await poller.scan_factory(factory["id"]) == 1
    assert await poller.scan_factory(factory["id"]) == 0
    assert len(store.list_jobs(factory["id"])) == 1
    assert store.list_jobs(factory["id"])[0]["issue_title"] == "Add export"


@pytest.mark.asyncio
async def test_failed_scan_does_not_advance_cursor(tmp_path: Path) -> None:
    store = FactoryStore(tmp_path / "factory.sqlite")
    factory = store.create_factory(
        owner_user_id="alice", repository_id=42, owner="acme", repo="widget"
    )
    poller = Poller(store, FakeIssues([issue(1), issue(2)], fail_at=2))
    with pytest.raises(OSError):
        await poller.scan_factory(factory["id"])
    assert store.get_factory(factory["id"])["poll_cursor"] is None
    assert len(store.list_jobs(factory["id"])) == 1

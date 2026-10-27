import pytest

from deerflow_code_factory.github.completion import GitHubCompletion
from deerflow_code_factory.github.pr_state import PullRequestSnapshot


class Gh:
    def __init__(self):
        self.calls = []

    async def api(self, path, *, method="GET", body=None):
        self.calls.append((method, path))
        if path.endswith("pulls/9"):
            return {
                "head": {"sha": "head1"},
                "state": "open",
                "merged": False,
                "title": "Export",
            }
        if path.endswith("pulls/9/merge"):
            return {"merged": True, "sha": "merge1"}
        if path.endswith("issues/7"):
            return {"labels": [{"name": "factory:ready"}]}
        if path.endswith("issues/7/labels"):
            return {"labels": ["factory:done"]}
        if path.endswith("issues/7/labels/factory%3Aready"):
            return {}
        raise AssertionError(path)


def snapshot(
    *,
    merged=False,
    checks=None,
    threads=(),
    reviews=(),
    requests=(),
    head="head1",
    merged_by="human",
):
    return PullRequestSnapshot(
        pr={
            "head": {"sha": head},
            "state": "open",
            "merged": merged,
            "merge_commit_sha": "merge1" if merged else None,
            "user": {"login": "factory-bot"},
            "title": "Export",
        },
        checks=tuple(
            checks
            if checks is not None
            else [{"name": "unit", "status": "completed", "conclusion": "success"}]
        ),
        statuses=(),
        reviews=tuple(reviews),
        threads=tuple(threads),
        review_requests=tuple(requests),
        merged_by=merged_by if merged else None,
        merged_at="2026-10-16T13:00:00Z" if merged else None,
    )


def approval(sha="head1", at="2026-10-16T12:00:00Z"):
    return {
        "id": 10,
        "state": "APPROVED",
        "commit_id": sha,
        "submitted_at": at,
        "user": {"login": "human", "type": "User"},
    }


@pytest.mark.asyncio
async def test_no_human_approval_blocks_merge(monkeypatch):
    async def fetch(*args):
        return snapshot()

    monkeypatch.setattr(
        "deerflow_code_factory.github.completion.fetch_pr_snapshot", fetch
    )
    gh = Gh()
    result = await GitHubCompletion(gh, approver_logins=("human",)).refresh(
        {"owner": "acme", "repo": "widget"},
        issue_number=7,
        pr_number=9,
        head_sha="head1",
    )
    assert result["state"] == "awaiting_approval"
    assert not gh.calls


@pytest.mark.asyncio
async def test_unresolved_thread_blocks_even_with_approval(monkeypatch):
    async def fetch(*args):
        return snapshot(
            reviews=[approval()],
            threads=[
                {
                    "id": "thread-1",
                    "isResolved": False,
                    "comments": {
                        "nodes": [
                            {
                                "id": "comment-1",
                                "body": "Fix this",
                                "author": {"login": "reviewer"},
                            }
                        ]
                    },
                }
            ],
        )

    monkeypatch.setattr(
        "deerflow_code_factory.github.completion.fetch_pr_snapshot", fetch
    )
    result = await GitHubCompletion(Gh(), approver_logins=("human",)).refresh(
        {"owner": "acme", "repo": "widget"},
        issue_number=7,
        pr_number=9,
        head_sha="head1",
    )
    assert result["state"] == "awaiting_review"
    assert result["feedback_ids"] == ["comment-1"]


@pytest.mark.asyncio
async def test_current_head_approval_allows_merge_after_recheck(monkeypatch):
    async def fetch(*args):
        return snapshot(reviews=[approval()])

    monkeypatch.setattr(
        "deerflow_code_factory.github.completion.fetch_pr_snapshot", fetch
    )
    gh = Gh()
    completion = GitHubCompletion(gh, approver_logins=("human",))
    state = await completion.refresh(
        {"owner": "acme", "repo": "widget"},
        issue_number=7,
        pr_number=9,
        head_sha="head1",
    )
    assert state["state"] == "awaiting_merge" and state["ready"] is True
    result = await completion.merge_if_ready(
        {"owner": "acme", "repo": "widget"},
        issue_number=7,
        pr_number=9,
        head_sha="head1",
    )
    assert result["state"] == "done"
    assert ("PUT", "repos/acme/widget/pulls/9/merge") in gh.calls


@pytest.mark.asyncio
async def test_manual_merge_is_detected_before_head_change(monkeypatch):
    async def fetch(*args):
        return snapshot(merged=True, head="new-head")

    monkeypatch.setattr(
        "deerflow_code_factory.github.completion.fetch_pr_snapshot", fetch
    )
    gh = Gh()
    result = await GitHubCompletion(gh, automation_login="factory-bot").refresh(
        {"owner": "acme", "repo": "widget"},
        issue_number=7,
        pr_number=9,
        head_sha="head1",
    )
    assert result["state"] == "merged_manual"
    assert result["merged_by"] == "human"
    assert ("POST", "repos/acme/widget/issues/7/labels") in gh.calls


@pytest.mark.asyncio
async def test_stale_approval_does_not_count(monkeypatch):
    async def fetch(*args):
        return snapshot(reviews=[approval("older")])

    monkeypatch.setattr(
        "deerflow_code_factory.github.completion.fetch_pr_snapshot", fetch
    )
    result = await GitHubCompletion(Gh(), approver_logins=("human",)).refresh(
        {"owner": "acme", "repo": "widget"},
        issue_number=7,
        pr_number=9,
        head_sha="head1",
    )
    assert result["state"] == "awaiting_approval"

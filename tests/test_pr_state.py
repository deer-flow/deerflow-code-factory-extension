import pytest

from deerflow_code_factory.github.pr_state import fetch_pr_snapshot


class Gh:
    def __init__(self, *, merged=False, thread_resolved=False, extra_page=False):
        self.merged = merged
        self.thread_resolved = thread_resolved
        self.extra_page = extra_page
        self.calls = []

    async def api(self, path, *, method="GET", body=None, paginate=False):
        self.calls.append(path)
        if path.endswith("/pulls/9"):
            return {
                "state": "open",
                "merged": self.merged,
                "head": {"sha": "a" * 40},
                "user": {"login": "factory-bot"},
                "title": "Add helper",
                "merge_commit_sha": "m" * 40 if self.merged else None,
            }
        if "check-runs" in path:
            return {
                "total_count": 1,
                "check_runs": [
                    {"name": "unit", "status": "completed", "conclusion": "success"}
                ],
            }
        if "/statuses?" in path:
            return [[]]
        if path.endswith("/reviews?per_page=100"):
            return [
                [
                    {
                        "id": 20,
                        "state": "APPROVED",
                        "commit_id": "a" * 40,
                        "submitted_at": "2026-10-16T12:00:00Z",
                        "user": {"login": "human", "type": "User"},
                    }
                ]
            ]
        if path == "graphql":
            return {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "mergedAt": "2026-10-16T13:00:00Z" if self.merged else None,
                            "mergedBy": {"login": "human"} if self.merged else None,
                            "reviewThreads": {
                                "nodes": [
                                    {
                                        "id": "thread-1",
                                        "isResolved": self.thread_resolved,
                                        "isOutdated": False,
                                        "path": "counter.py",
                                        "comments": {
                                            "nodes": [
                                                {
                                                    "id": "comment-1",
                                                    "body": "Handle zero",
                                                    "author": {"login": "reviewer"},
                                                }
                                            ],
                                            "pageInfo": {
                                                "hasNextPage": False,
                                                "endCursor": None,
                                            },
                                        },
                                    }
                                ],
                                "pageInfo": {
                                    "hasNextPage": self.extra_page,
                                    "endCursor": "cursor" if self.extra_page else None,
                                },
                            },
                            "reviewRequests": {
                                "nodes": [],
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                            },
                        }
                    }
                }
            }
        raise AssertionError(path)


@pytest.mark.asyncio
async def test_fetch_pr_snapshot_collects_checks_approvals_and_threads():
    snapshot = await fetch_pr_snapshot(Gh(), {"owner": "acme", "repo": "widget"}, 9)
    assert snapshot.head_sha == "a" * 40
    assert snapshot.checks[0]["name"] == "unit"
    assert snapshot.reviews[0]["user"]["login"] == "human"
    assert snapshot.threads[0]["isResolved"] is False
    assert snapshot.feedback_ids == ("comment-1",)


@pytest.mark.asyncio
async def test_snapshot_requires_complete_graphql_pages():
    gh = Gh(extra_page=True)
    with pytest.raises(RuntimeError, match="pagination"):
        await fetch_pr_snapshot(gh, {"owner": "acme", "repo": "widget"}, 9)

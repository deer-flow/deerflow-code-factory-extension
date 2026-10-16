import pytest

from deerflow_code_factory.github.completion import GitHubCompletion


class FakeGh:
    def __init__(self, checks, *, merged=False):
        self.checks = checks
        self.merged = merged
        self.calls = []

    async def api(self, path, *, method="GET", body=None):
        self.calls.append((method, path))
        if path.endswith("pulls/9"):
            return {
                "head": {"sha": "head1"},
                "state": "open",
                "merged": self.merged,
                "merge_commit_sha": "merge1" if self.merged else None,
                "title": "Export",
            }
        if "check-runs" in path:
            return {"check_runs": self.checks}
        if path.endswith("/status"):
            return {"statuses": []}
        if path.endswith("pulls/9/merge"):
            return {"merged": True, "sha": "merge1"}
        if path.endswith("issues/7/labels"):
            return {"labels": ["factory:done"]}
        if path.endswith("issues/7"):
            return {"labels": [{"name": "factory:ready"}]}
        if path.endswith("issues/7/labels/factory%3Aready") and method == "DELETE":
            return {}
        raise AssertionError(path)


@pytest.mark.asyncio
async def test_merge_only_after_head_bound_checks_pass():
    factory = {"owner": "acme", "repo": "widget"}
    gh = FakeGh([{"status": "completed", "conclusion": "success"}])
    result = await GitHubCompletion(gh).refresh(
        factory, issue_number=7, pr_number=9, head_sha="head1"
    )
    assert result == {"state": "done", "merge_sha": "merge1"}
    assert ("PUT", "repos/acme/widget/pulls/9/merge") in gh.calls
    assert ("POST", "repos/acme/widget/issues/7/labels") in gh.calls
    assert ("DELETE", "repos/acme/widget/issues/7/labels/factory%3Aready") in gh.calls


@pytest.mark.asyncio
async def test_already_merged_pr_finishes_issue_labels():
    gh = FakeGh([], merged=True)
    result = await GitHubCompletion(gh).refresh(
        {"owner": "acme", "repo": "widget"},
        issue_number=7,
        pr_number=9,
        head_sha="head1",
    )
    assert result == {"state": "done", "merge_sha": "merge1"}
    assert ("POST", "repos/acme/widget/issues/7/labels") in gh.calls
    assert ("DELETE", "repos/acme/widget/issues/7/labels/factory%3Aready") in gh.calls


@pytest.mark.asyncio
async def test_failed_checks_block_merge():
    gh = FakeGh([{"status": "completed", "conclusion": "failure"}])
    result = await GitHubCompletion(gh).refresh(
        {"owner": "acme", "repo": "widget"},
        issue_number=7,
        pr_number=9,
        head_sha="head1",
    )
    assert result["state"] == "failed_checks"
    assert not any(method == "PUT" for method, _ in gh.calls)

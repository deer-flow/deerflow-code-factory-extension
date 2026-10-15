import pytest

from deerflow_code_factory.github.delivery import GitHubDelivery, validate_files


def test_file_validation_rejects_paths_outside_repository():
    for path in (
        "../secret",
        "/tmp/file",
        ".github/workflows/deploy.yml",
        ".git/config",
    ):
        with pytest.raises(ValueError):
            validate_files([{"path": path, "content": "data"}])


class FakeGh:
    def __init__(self):
        self.calls = []

    async def api(self, path, *, method="GET", body=None):
        self.calls.append((method, path, body))
        if path.endswith("git/ref/heads/main"):
            return {"object": {"sha": "base"}}
        if path.endswith("git/refs"):
            return {"ref": "refs/heads/code-factory/issue-7"}
        if path.endswith("git/commits/base"):
            return {"tree": {"sha": "tree0"}}
        if path.endswith("git/trees"):
            return {"sha": "tree1"}
        if path.endswith("git/commits"):
            return {"sha": "head1"}
        if path.endswith("git/refs/heads/code-factory/issue-7"):
            return {"object": {"sha": "head1"}}
        if path.endswith("pulls"):
            return {
                "number": 9,
                "html_url": "https://github.com/acme/widget/pull/9",
                "head": {"sha": "head1"},
            }
        raise AssertionError(path)


@pytest.mark.asyncio
async def test_delivery_commits_one_tree_and_creates_pr():
    gh = FakeGh()
    delivery = GitHubDelivery(gh)
    result = await delivery.deliver(
        {"owner": "acme", "repo": "widget"},
        issue_number=7,
        base_branch="main",
        files=[{"path": "src/export.py", "content": "print('ok')\n"}],
        title="Add export",
        description="Implements #7",
    )
    assert result["head_sha"] == "head1"
    assert result["pr_number"] == 9
    tree = next(body for method, path, body in gh.calls if path.endswith("git/trees"))
    assert tree["base_tree"] == "tree0"
    assert tree["tree"][0]["path"] == "src/export.py"

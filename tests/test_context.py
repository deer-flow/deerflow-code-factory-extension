import pytest

from deerflow_code_factory.github.context import load_repository_context


class FakeGh:
    async def api(self, path):
        if path.endswith("git/ref/heads/main"):
            return {"object": {"sha": "base"}}
        if path.endswith("git/commits/base"):
            return {"tree": {"sha": "tree"}}
        if "git/trees/tree" in path:
            return {"tree": [{"path": "README.md", "type": "blob"}], "truncated": False}
        raise AssertionError(path)


@pytest.mark.asyncio
async def test_new_file_in_relevant_paths_is_skipped():
    context = await load_repository_context(
        FakeGh(), {"owner": "acme", "repo": "widget"}, "main", ["counter.py"]
    )
    assert "README.md" in context

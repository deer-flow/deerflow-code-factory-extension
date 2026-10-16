import json
from datetime import datetime, timezone

import pytest

from deerflow_code_factory.github.gh_cli import (
    GhClient,
    GhIssueSource,
    GhRepositorySetup,
)
from deerflow_code_factory.requirements import IssueRef


class FakeGh:
    def __init__(self, results):
        self.results = results
        self.calls = []

    async def api(self, path, *, method="GET", fields=None, paginate=False):
        self.calls.append((method, path, fields, paginate))
        return self.results.pop(0)


@pytest.mark.asyncio
async def test_cli_issue_source_reads_candidates_and_excludes_prs():
    gh = FakeGh(
        [
            [[{"id": 10, "number": 1}, {"id": 20, "number": 2, "pull_request": {}}]],
            {
                "id": 10,
                "number": 1,
                "title": "Export",
                "body": "CSV",
                "user": {"id": 9},
                "state": "open",
                "labels": [{"name": "factory:ready"}],
                "updated_at": "2026-10-15T01:00:00Z",
            },
        ]
    )
    source = GhIssueSource(gh)
    factory = {"owner": "acme", "repo": "widget"}
    refs = await source.list_candidates(
        factory, datetime(2026, 10, 14, tzinfo=timezone.utc)
    )
    assert refs == [IssueRef(10, 1)]
    snapshot = await source.fetch(factory, refs[0])
    assert snapshot.title == "Export"
    assert "since=2026-10-14T00%3A00%3A00Z" in gh.calls[0][1]


@pytest.mark.asyncio
async def test_cli_setup_validates_and_creates_only_missing_labels():
    gh = FakeGh(
        [
            {
                "id": 42,
                "full_name": "acme/widget",
                "default_branch": "main",
                "has_issues": True,
                "archived": False,
            },
            [[{"name": "factory:ready"}]],
            {"name": "factory:done"},
        ]
    )
    setup = GhRepositorySetup(gh)
    report = await setup.validate("acme", "widget")
    assert report.ready and "factory:ready" not in report.missing_labels
    # One response is needed for each missing label.
    gh.results.extend({"name": label} for label in report.missing_labels[1:])
    assert await setup.ensure_labels("acme", "widget", report) == report.missing_labels
    assert len([call for call in gh.calls if call[0] == "POST"]) == len(
        report.missing_labels
    )


@pytest.mark.asyncio
async def test_cli_invocation_never_uses_shell(monkeypatch):
    captured = []

    def run(argv, **kwargs):
        captured.append((argv, kwargs))
        return type(
            "Result",
            (),
            {"returncode": 0, "stdout": json.dumps({"id": 42}), "stderr": ""},
        )()

    monkeypatch.setattr("subprocess.run", run)
    assert await GhClient().api("repos/acme/widget") == {"id": 42}
    assert captured[0][0][:3] == ["gh", "api", "repos/acme/widget"]
    assert captured[0][1]["shell"] is False
    await GhClient().api(
        "repos/acme/widget/issues/7/labels/factory%3Aready", method="DELETE"
    )
    assert captured[1][0][-2:] == ["--method", "DELETE"]


@pytest.mark.asyncio
async def test_cli_setup_rejects_explicit_read_only_access():
    gh = FakeGh(
        [
            {
                "id": 42,
                "full_name": "acme/widget",
                "default_branch": "main",
                "has_issues": True,
                "archived": False,
                "permissions": {"push": False},
            }
        ]
    )
    report = await GhRepositorySetup(gh).validate("acme", "widget")
    assert report.problems == ("push_permission",)
    assert len(gh.calls) == 1

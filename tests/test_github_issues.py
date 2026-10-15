from datetime import datetime, timezone

import httpx
import pytest

from deerflow_code_factory.github.issues import GitHubIssueSource
from deerflow_code_factory.requirements import IssueRef


@pytest.mark.asyncio
async def test_list_candidates_paginates_and_fetches_issue() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        assert request.headers["Authorization"] == "Bearer secret"
        if request.url.path.endswith("/issues/7"):
            return httpx.Response(
                200,
                json={
                    "id": 70,
                    "number": 7,
                    "title": "Export",
                    "body": "CSV",
                    "user": {"id": 9},
                    "state": "open",
                    "labels": [{"name": "factory:ready"}],
                    "updated_at": "2026-10-15T01:00:00Z",
                },
            )
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json=[{"id": 80, "number": 8}])
        return httpx.Response(
            200,
            json=[{"id": 70, "number": 7}],
            headers={
                "Link": '<https://api.github.com/repos/acme/widget/issues?page=2>; rel="next"'
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    ) as client:
        source = GitHubIssueSource(client, token_provider=lambda _: "secret")
        factory = {"repository_id": 42, "owner": "acme", "repo": "widget"}
        refs = await source.list_candidates(
            factory, datetime(2026, 10, 14, tzinfo=timezone.utc)
        )
        ticket = await source.fetch(factory, IssueRef(70, 7))
    assert refs == [IssueRef(70, 7), IssueRef(80, 8)]
    assert ticket.issue_id == 70
    assert ticket.labels == frozenset({"factory:ready"})
    assert "since=" in requests[0]


@pytest.mark.asyncio
async def test_list_candidates_rejects_api_failure() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "forbidden"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    ) as client:
        source = GitHubIssueSource(client, token_provider=lambda _: "secret")
        with pytest.raises(httpx.HTTPStatusError):
            await source.list_candidates(
                {"repository_id": 42, "owner": "acme", "repo": "widget"}, None
            )

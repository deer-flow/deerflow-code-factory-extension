import httpx
import pytest

from deerflow_code_factory.github.setup import GitHubRepositorySetup


@pytest.mark.asyncio
async def test_validate_existing_repository_and_create_only_missing_labels() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        assert request.headers["Authorization"] == "Bearer secret"
        if request.url.path == "/repos/acme/widget":
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "full_name": "acme/widget",
                    "default_branch": "main",
                    "has_issues": True,
                    "archived": False,
                    "permissions": {"push": True},
                },
            )
        if request.url.path == "/repos/acme/widget/labels" and request.method == "GET":
            return httpx.Response(200, json=[{"name": "factory:ready"}])
        if request.url.path == "/repos/acme/widget/labels" and request.method == "POST":
            return httpx.Response(201, json={"name": "created"})
        raise AssertionError(str(request.url))

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    ) as client:
        setup = GitHubRepositorySetup(client, lambda: "secret")
        report = await setup.validate("acme", "widget")
        assert report.repository_id == 42
        assert report.missing_labels
        assert report.ready is True
        created = await setup.ensure_labels("acme", "widget", report)
    assert set(created) == set(report.missing_labels)
    assert calls.count(("POST", "/repos/acme/widget/labels")) == len(created)


@pytest.mark.asyncio
async def test_validate_rejects_repository_without_usable_default_branch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/acme/empty":
            return httpx.Response(
                200,
                json={
                    "id": 7,
                    "full_name": "acme/empty",
                    "default_branch": None,
                    "has_issues": True,
                    "archived": False,
                    "permissions": {"push": True},
                },
            )
        raise AssertionError(str(request.url))

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    ) as client:
        report = await GitHubRepositorySetup(client, lambda: "secret").validate(
            "acme", "empty"
        )
    assert not report.ready
    assert "default_branch" in report.problems

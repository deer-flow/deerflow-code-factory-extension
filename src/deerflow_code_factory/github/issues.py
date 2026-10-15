"""Read GitHub Issues without leaking App credentials into Agent runs."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx

from ..requirements import IssueRef, RequirementSnapshot


class GitHubIssueSource:
    def __init__(
        self, client: httpx.AsyncClient, token_provider: Callable[[dict[str, Any]], str]
    ):
        self.client = client
        self.token_provider = token_provider

    def _headers(self, factory: dict[str, Any]) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token_provider(factory)}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    @staticmethod
    def _path(factory: dict[str, Any]) -> str:
        return f"/repos/{factory['owner']}/{factory['repo']}/issues"

    async def list_candidates(
        self, factory: dict[str, Any], since: datetime | None
    ) -> list[IssueRef]:
        params: dict[str, str | int] = {
            "state": "open",
            "labels": "factory:ready",
            "sort": "updated",
            "direction": "asc",
            "per_page": 100,
        }
        if since is not None:
            params["since"] = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        refs: list[IssueRef] = []
        for page in range(1, 101):
            response = await self.client.get(
                self._path(factory),
                headers=self._headers(factory),
                params={**params, "page": page},
            )
            response.raise_for_status()
            refs.extend(
                IssueRef(issue_id=row["id"], number=row["number"])
                for row in response.json()
            )
            if "next" not in response.links:
                return refs
        raise RuntimeError("GitHub issue pagination exceeded 100 pages")

    async def fetch(
        self, factory: dict[str, Any], ref: IssueRef
    ) -> RequirementSnapshot:
        response = await self.client.get(
            f"{self._path(factory)}/{ref.number}", headers=self._headers(factory)
        )
        response.raise_for_status()
        row = response.json()
        if row["id"] != ref.issue_id:
            raise ValueError("issue identity changed")
        return RequirementSnapshot(
            issue_id=row["id"],
            number=row["number"],
            title=row.get("title") or "",
            body=row.get("body") or "",
            author_id=row["user"]["id"],
            state=row["state"],
            labels=frozenset(label["name"] for label in row.get("labels", [])),
            updated_at=datetime.fromisoformat(row["updated_at"].replace("Z", "+00:00")),
            is_pull_request="pull_request" in row,
        )

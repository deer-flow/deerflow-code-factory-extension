"""Validate a bound GitHub repository and provision the factory's issue labels."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

import httpx


LABELS = {
    "factory:ready": "1d76db",
    "factory:planning": "5319e7",
    "factory:blocked": "d93f0b",
    "factory:building": "fbca04",
    "factory:review": "0e8a16",
    "factory:done": "006b75",
}
_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class ValidationReport:
    repository_id: int
    owner: str
    repo: str
    missing_labels: tuple[str, ...]
    problems: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.problems


class GitHubRepositorySetup:
    def __init__(self, client: httpx.AsyncClient, token_provider: Callable[[], str]):
        self.client = client
        self.token_provider = token_provider

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token_provider()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    @staticmethod
    def _path(owner: str, repo: str) -> str:
        if not _NAME.fullmatch(owner) or not _NAME.fullmatch(repo):
            raise ValueError("invalid GitHub repository name")
        return f"/repos/{owner}/{repo}"

    async def validate(self, owner: str, repo: str) -> ValidationReport:
        path = self._path(owner, repo)
        response = await self.client.get(path, headers=self._headers())
        response.raise_for_status()
        data = response.json()
        if data.get("full_name", "").casefold() != f"{owner}/{repo}".casefold():
            raise ValueError("repository identity mismatch")
        problems = []
        if not data.get("default_branch"):
            problems.append("default_branch")
        if not data.get("has_issues"):
            problems.append("issues_disabled")
        if data.get("archived"):
            problems.append("archived")
        # GitHub App installation repo responses may omit permissions. A write
        # operation will still be checked by GitHub when labels are created.
        permissions = data.get("permissions")
        if permissions is not None and not permissions.get("push"):
            problems.append("push_permission")
        if problems:
            return ValidationReport(data["id"], owner, repo, (), tuple(problems))
        existing = set()
        for page in range(1, 101):
            labels = await self.client.get(
                f"{path}/labels",
                headers=self._headers(),
                params={"per_page": 100, "page": page},
            )
            labels.raise_for_status()
            existing.update(row["name"] for row in labels.json())
            if "next" not in labels.links:
                break
        else:
            raise RuntimeError("GitHub label pagination exceeded 100 pages")
        return ValidationReport(
            repository_id=data["id"],
            owner=owner,
            repo=repo,
            missing_labels=tuple(name for name in LABELS if name not in existing),
            problems=tuple(problems),
        )

    async def ensure_labels(
        self, owner: str, repo: str, report: ValidationReport
    ) -> tuple[str, ...]:
        if not report.ready or (owner, repo) != (report.owner, report.repo):
            raise ValueError("repository validation is required")
        path = self._path(owner, repo)
        created = []
        for name in report.missing_labels:
            response = await self.client.post(
                f"{path}/labels",
                headers=self._headers(),
                json={"name": name, "color": LABELS[name]},
            )
            response.raise_for_status()
            created.append(name)
        return tuple(created)

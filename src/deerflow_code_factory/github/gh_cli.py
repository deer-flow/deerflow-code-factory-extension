"""GitHub adapter using the operator's authenticated gh CLI session."""

from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

from ..requirements import IssueRef, RequirementSnapshot
from .setup import LABELS, ValidationReport


class GhError(RuntimeError):
    pass


class GhClient:
    async def api(
        self,
        path: str,
        *,
        method: str = "GET",
        fields: dict[str, str] | None = None,
        paginate: bool = False,
    ) -> Any:
        if not path or path.startswith("-") or method not in {"GET", "POST"}:
            raise ValueError("invalid gh api request")
        argv = ["gh", "api", path, "--method", method]
        if paginate:
            argv.extend(["--paginate", "--slurp"])
        for key, value in (fields or {}).items():
            argv.extend(["--field", f"{key}={value}"])

        def invoke() -> Any:
            try:
                result = subprocess.run(
                    argv,
                    capture_output=True,
                    text=True,
                    timeout=25,
                    shell=False,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise GhError("gh CLI unavailable or timed out") from exc
            if result.returncode:
                # gh may print request URLs and account details to stderr.
                raise GhError(f"gh api failed (exit {result.returncode})")
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                raise GhError("gh api returned invalid JSON") from exc

        return await asyncio.to_thread(invoke)


class GhIssueSource:
    def __init__(self, gh: GhClient):
        self.gh = gh

    @staticmethod
    def _path(factory: dict[str, Any]) -> str:
        return f"repos/{factory['owner']}/{factory['repo']}/issues"

    async def list_candidates(
        self, factory: dict[str, Any], since: datetime | None
    ) -> list[IssueRef]:
        params = {"state": "open", "labels": "factory:ready", "per_page": "100"}
        if since:
            params["since"] = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        pages = await self.gh.api(
            f"{self._path(factory)}?{urlencode(params)}", paginate=True
        )
        rows = [row for page in pages for row in page]
        return [
            IssueRef(row["id"], row["number"])
            for row in rows
            if "pull_request" not in row
        ]

    async def fetch(
        self, factory: dict[str, Any], ref: IssueRef
    ) -> RequirementSnapshot:
        row = await self.gh.api(f"{self._path(factory)}/{ref.number}")
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


class GhRepositorySetup:
    def __init__(self, gh: GhClient):
        self.gh = gh

    @staticmethod
    def _path(owner: str, repo: str) -> str:
        from .setup import GitHubRepositorySetup

        return GitHubRepositorySetup._path(owner, repo).lstrip("/")

    async def validate(self, owner: str, repo: str) -> ValidationReport:
        path = self._path(owner, repo)
        data = await self.gh.api(path)
        if data.get("full_name", "").casefold() != f"{owner}/{repo}".casefold():
            raise ValueError("repository identity mismatch")
        problems = []
        if not data.get("default_branch"):
            problems.append("default_branch")
        if not data.get("has_issues"):
            problems.append("issues_disabled")
        if data.get("archived"):
            problems.append("archived")
        permissions = data.get("permissions")
        if permissions is not None and not permissions.get("push"):
            problems.append("push_permission")
        if problems:
            return ValidationReport(data["id"], owner, repo, (), tuple(problems))
        pages = await self.gh.api(f"{path}/labels?per_page=100", paginate=True)
        existing = {row["name"] for page in pages for row in page}
        return ValidationReport(
            data["id"],
            owner,
            repo,
            tuple(name for name in LABELS if name not in existing),
            (),
        )

    async def ensure_labels(
        self, owner: str, repo: str, report: ValidationReport
    ) -> tuple[str, ...]:
        if not report.ready or (owner, repo) != (report.owner, report.repo):
            raise ValueError("repository validation is required")
        path = self._path(owner, repo)
        for name in report.missing_labels:
            await self.gh.api(
                f"{path}/labels",
                method="POST",
                fields={"name": name, "color": LABELS[name]},
            )
        return report.missing_labels

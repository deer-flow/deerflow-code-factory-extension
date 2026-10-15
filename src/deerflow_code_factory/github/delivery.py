"""Commit reviewed text files atomically through GitHub's Git Data API."""

from __future__ import annotations

from typing import Any

from .gh_cli import GhClient


def validate_files(files: list[dict[str, str]]) -> list[dict[str, str]]:
    if not isinstance(files, list) or not 1 <= len(files) <= 50:
        raise ValueError("expected 1–50 changed files")
    total = 0
    seen = set()
    for item in files:
        if not isinstance(item, dict) or set(item) != {"path", "content"}:
            raise ValueError("invalid file object")
        path, content = item["path"], item["content"]
        if not isinstance(path, str) or not isinstance(content, str):
            raise ValueError("file path and content must be text")
        parts = path.split("/")
        if (
            not path
            or path.startswith("/")
            or "\\" in path
            or any(part in {"", ".", ".."} for part in parts)
            or parts[0] in {".git", ".github"}
            or path in seen
        ):
            raise ValueError("unsafe repository path")
        seen.add(path)
        total += len(content.encode("utf-8"))
        if total > 256_000:
            raise ValueError("changed files exceed 256 KiB")
    return files


class GitHubDelivery:
    def __init__(self, gh: GhClient):
        self.gh = gh

    async def deliver(
        self,
        factory: dict[str, Any],
        *,
        issue_number: int,
        base_branch: str,
        files: list[dict[str, str]],
        title: str,
        description: str,
    ) -> dict[str, Any]:
        validate_files(files)
        if (
            issue_number <= 0
            or not base_branch
            or "/" in base_branch
            or ".." in base_branch
        ):
            raise ValueError("invalid issue or base branch")
        root = f"repos/{factory['owner']}/{factory['repo']}"
        branch = f"code-factory/issue-{issue_number}"
        base = await self.gh.api(f"{root}/git/ref/heads/{base_branch}")
        base_sha = base["object"]["sha"]
        await self.gh.api(
            f"{root}/git/refs",
            method="POST",
            body={"ref": f"refs/heads/{branch}", "sha": base_sha},
        )
        base_commit = await self.gh.api(f"{root}/git/commits/{base_sha}")
        tree = await self.gh.api(
            f"{root}/git/trees",
            method="POST",
            body={
                "base_tree": base_commit["tree"]["sha"],
                "tree": [
                    {
                        "path": item["path"],
                        "mode": "100644",
                        "type": "blob",
                        "content": item["content"],
                    }
                    for item in files
                ],
            },
        )
        commit = await self.gh.api(
            f"{root}/git/commits",
            method="POST",
            body={
                "message": f"Implement issue #{issue_number}",
                "tree": tree["sha"],
                "parents": [base_sha],
            },
        )
        head_sha = commit["sha"]
        await self.gh.api(
            f"{root}/git/refs/heads/{branch}",
            method="PATCH",
            body={"sha": head_sha, "force": False},
        )
        pr = await self.gh.api(
            f"{root}/pulls",
            method="POST",
            body={
                "title": title[:120],
                "body": description[:10000],
                "head": branch,
                "base": base_branch,
                "draft": False,
            },
        )
        return {
            "pr_number": pr["number"],
            "pr_url": pr["html_url"],
            "head_sha": head_sha,
            "base_sha": base_sha,
        }

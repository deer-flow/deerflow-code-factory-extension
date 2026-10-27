"""Commit reviewed text files atomically through GitHub's Git Data API."""

from __future__ import annotations

import re
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

    async def post_review_summary(
        self, factory: dict[str, Any], pr_number: int, head_sha: str, summary: str
    ) -> None:
        root = f"repos/{factory['owner']}/{factory['repo']}"
        marker = f"<!-- deerflow-code-factory-review:{head_sha} -->"
        pages = await self.gh.api(
            f"{root}/issues/{pr_number}/comments?per_page=100", paginate=True
        )
        if any(marker in (item.get("body") or "") for page in pages for item in page):
            return
        await self.gh.api(
            f"{root}/issues/{pr_number}/comments",
            method="POST",
            body={"body": f"{marker}\n{summary[:9000]}"},
        )

    async def reply_to_review_thread(self, thread_id: str, body: str) -> None:
        response = await self.gh.api(
            "graphql",
            method="POST",
            body={
                "query": "mutation($id:ID!,$body:String!){addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:$id,body:$body}){comment{id}}}",
                "variables": {"id": thread_id, "body": body[:3000]},
            },
        )
        if response.get("errors") or not response.get("data", {}).get(
            "addPullRequestReviewThreadReply"
        ):
            raise RuntimeError("could not reply to PR review thread")

    async def create_pull_request_for_branch(
        self,
        factory: dict[str, Any],
        *,
        issue_number: int,
        head_branch: str,
        base_branch: str,
        head_sha: str,
        base_sha: str,
        title: str,
        description: str,
    ) -> dict[str, Any]:
        if (
            issue_number <= 0
            or not head_sha
            or not base_sha
            or not re.fullmatch(
                rf"code-factory/issue-{issue_number}-run-[0-9]+", head_branch
            )
        ):
            raise ValueError("invalid pull request source")
        root = f"repos/{factory['owner']}/{factory['repo']}"
        pr = await self.gh.api(
            f"{root}/pulls",
            method="POST",
            body={
                "title": title[:120],
                "body": description[:10000],
                "head": head_branch,
                "base": base_branch,
                "draft": False,
            },
        )
        return {
            "pr_number": pr["number"],
            "pr_url": pr["html_url"],
            "head_branch": head_branch,
            "head_sha": head_sha,
            "base_sha": base_sha,
        }

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

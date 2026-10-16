"""Head-bound CI and GitHub merge-policy gate for an existing PR."""

from .gh_cli import GhClient, GhError


class GitHubCompletion:
    def __init__(self, gh: GhClient):
        self.gh = gh

    async def _finish_issue_labels(self, root: str, issue_number: int) -> None:
        issue_path = f"{root}/issues/{issue_number}"
        issue = await self.gh.api(issue_path)
        labels = {label["name"] for label in issue.get("labels", [])}
        if "factory:done" not in labels:
            await self.gh.api(
                f"{issue_path}/labels",
                method="POST",
                body={"labels": ["factory:done"]},
            )
        if "factory:ready" in labels:
            await self.gh.api(f"{issue_path}/labels/factory%3Aready", method="DELETE")

    async def refresh(
        self, factory, *, issue_number: int, pr_number: int, head_sha: str
    ) -> dict:
        root = f"repos/{factory['owner']}/{factory['repo']}"
        pr = await self.gh.api(f"{root}/pulls/{pr_number}")
        if pr["head"]["sha"] != head_sha:
            return {"state": "stale_head"}
        if pr.get("merged"):
            await self._finish_issue_labels(root, issue_number)
            return {"state": "done", "merge_sha": pr.get("merge_commit_sha")}
        if pr.get("state") != "open":
            return {"state": "closed"}
        checks = await self.gh.api(f"{root}/commits/{head_sha}/check-runs?per_page=100")
        runs = checks.get("check_runs", [])
        status = await self.gh.api(f"{root}/commits/{head_sha}/status")
        contexts = status.get("statuses", [])
        if not runs and not contexts:
            return {"state": "awaiting_checks", "reason": "no CI checks reported"}
        if any(run.get("status") != "completed" for run in runs) or any(
            item.get("state") == "pending" for item in contexts
        ):
            return {"state": "awaiting_checks"}
        if any(
            run.get("conclusion") not in {"success", "neutral", "skipped"}
            for run in runs
        ) or any(item.get("state") != "success" for item in contexts):
            return {"state": "failed_checks"}
        try:
            merged = await self.gh.api(
                f"{root}/pulls/{pr_number}/merge",
                method="PUT",
                body={
                    "sha": head_sha,
                    "merge_method": "squash",
                    "commit_title": pr["title"][:120],
                },
            )
        except GhError:
            # GitHub rejects merges when required approval or branch rules are unmet.
            return {"state": "awaiting_merge"}
        if not merged.get("merged"):
            return {"state": "awaiting_merge"}
        await self._finish_issue_labels(root, issue_number)
        return {"state": "done", "merge_sha": merged.get("sha")}

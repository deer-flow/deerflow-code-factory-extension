"""Fail-closed PR review, check and human-approval merge gates."""

from __future__ import annotations

from datetime import datetime

from .gh_cli import GhClient, GhError
from .pr_state import PullRequestSnapshot, fetch_pr_snapshot


def _instant(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class GitHubCompletion:
    def __init__(
        self,
        gh: GhClient,
        *,
        required_checks: tuple[str, ...] = (),
        approver_logins: tuple[str, ...] = (),
        automation_login: str | None = None,
    ):
        self.gh = gh
        self.required_checks = required_checks
        self.approver_logins = {value.casefold() for value in approver_logins}
        self.automation_login = (
            automation_login.casefold() if automation_login else None
        )

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

    def _evaluate(self, snapshot: PullRequestSnapshot, head_sha: str) -> dict:
        pr = snapshot.pr
        if pr["head"]["sha"] != head_sha:
            return {
                "state": "stale_head",
                "reason": "PR head changed",
                "head_sha": snapshot.head_sha,
            }
        if pr.get("state") != "open":
            return {"state": "closed", "reason": "PR is closed"}

        checks = list(snapshot.checks)
        latest_statuses = {}
        for item in snapshot.statuses:
            latest_statuses.setdefault(item.get("context"), item)
        observed_names = {item.get("name") for item in checks} | set(latest_statuses)
        if not checks and not latest_statuses:
            return {"state": "awaiting_checks", "reason": "no CI checks reported"}
        missing = sorted(set(self.required_checks) - observed_names)
        if missing:
            return {
                "state": "awaiting_checks",
                "reason": f"required checks missing: {', '.join(missing)}",
            }
        if any(item.get("status") != "completed" for item in checks) or any(
            item.get("state") == "pending" for item in latest_statuses.values()
        ):
            return {"state": "awaiting_checks", "reason": "checks still running"}
        if any(item.get("conclusion") != "success" for item in checks) or any(
            item.get("state") != "success" for item in latest_statuses.values()
        ):
            return {"state": "failed_checks", "reason": "checks did not pass"}

        latest_reviews = {}
        for review in snapshot.reviews:
            user = review.get("user") or {}
            login = user.get("login")
            if login:
                latest_reviews[login.casefold()] = review
        blocked_reviews = [
            review
            for review in latest_reviews.values()
            if review.get("state") == "CHANGES_REQUESTED"
        ]
        open_threads = [
            thread for thread in snapshot.threads if not thread.get("isResolved")
        ]
        feedback_ids = [
            str(comment["id"])
            for thread in open_threads
            for comment in thread.get("comments", {}).get("nodes", [])
            if (comment.get("author") or {}).get("login", "").casefold()
            != self.automation_login
        ] + [f"review:{review['id']}" for review in blocked_reviews]
        feedback = [
            {
                "id": str(comment["id"]),
                "body": (comment.get("body") or "")[:3000],
                "path": thread.get("path") or "",
                "thread_id": thread["id"],
            }
            for thread in open_threads
            for comment in thread.get("comments", {}).get("nodes", [])
            if (comment.get("author") or {}).get("login", "").casefold()
            != self.automation_login
        ] + [
            {
                "id": f"review:{review['id']}",
                "body": (review.get("body") or "")[:3000],
                "path": "",
                "thread_id": None,
            }
            for review in blocked_reviews
        ]
        if open_threads or blocked_reviews or snapshot.review_requests:
            return {
                "state": "awaiting_review",
                "reason": "review feedback or requested review pending",
                "feedback_ids": feedback_ids,
                "feedback": feedback,
                "head_sha": head_sha,
            }

        feedback_times = [
            _instant(comment.get("createdAt"))
            for thread in snapshot.threads
            for comment in thread.get("comments", {}).get("nodes", [])
        ] + [
            _instant(review.get("submitted_at"))
            for review in snapshot.reviews
            if review.get("state") != "APPROVED"
        ]
        latest_feedback = max(
            (item for item in feedback_times if item is not None), default=None
        )
        author = (pr.get("user") or {}).get("login", "").casefold()
        approved = any(
            login in self.approver_logins
            and login != author
            and login != self.automation_login
            and review.get("state") == "APPROVED"
            and review.get("commit_id") == head_sha
            and (review.get("user") or {}).get("type") == "User"
            and (
                latest_feedback is None
                or (
                    _instant(review.get("submitted_at"))
                    or datetime.min.replace(tzinfo=latest_feedback.tzinfo)
                )
                > latest_feedback
            )
            for login, review in latest_reviews.items()
        )
        if not approved:
            return {
                "state": "awaiting_approval",
                "reason": "current head needs final human approval",
                "head_sha": head_sha,
            }
        return {"state": "awaiting_merge", "ready": True, "head_sha": head_sha}

    async def refresh(
        self,
        factory: dict,
        *,
        issue_number: int,
        pr_number: int,
        head_sha: str,
        prior_merge_attempt: bool = False,
    ) -> dict:
        root = f"repos/{factory['owner']}/{factory['repo']}"
        snapshot = await fetch_pr_snapshot(self.gh, factory, pr_number)
        if snapshot.pr.get("merged"):
            await self._finish_issue_labels(root, issue_number)
            actor = snapshot.merged_by
            if not prior_merge_attempt:
                state = "merged_manual"
            elif (
                actor
                and self.automation_login
                and actor.casefold() != self.automation_login
            ):
                state = "merged_manual"
            else:
                state = "merged_unknown"
            return {
                "state": state,
                "merge_sha": snapshot.pr.get("merge_commit_sha"),
                "merged_by": actor,
                "merged_at": snapshot.merged_at,
            }
        return self._evaluate(snapshot, head_sha)

    async def merge_if_ready(
        self, factory: dict, *, issue_number: int, pr_number: int, head_sha: str
    ) -> dict:
        current = await self.refresh(
            factory,
            issue_number=issue_number,
            pr_number=pr_number,
            head_sha=head_sha,
            prior_merge_attempt=True,
        )
        if current.get("state") != "awaiting_merge" or not current.get("ready"):
            return current
        root = f"repos/{factory['owner']}/{factory['repo']}"
        pr = await self.gh.api(f"{root}/pulls/{pr_number}")
        if (
            pr.get("merged")
            or pr.get("state") != "open"
            or pr["head"]["sha"] != head_sha
        ):
            return {
                "state": "awaiting_merge",
                "reason": "PR changed before merge; recheck required",
            }
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
            return {
                "state": "awaiting_merge",
                "reason": "GitHub rejected merge or outcome is uncertain",
            }
        if not merged.get("merged"):
            return {"state": "awaiting_merge", "reason": "GitHub did not merge PR"}
        await self._finish_issue_labels(root, issue_number)
        return {"state": "done", "merge_sha": merged.get("sha")}

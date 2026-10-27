"""Complete, bounded GitHub evidence for one pull request."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .gh_cli import GhClient, GhError

_QUERY = """
query($owner:String!,$repo:String!,$number:Int!,$threads:String,$requests:String){
  repository(owner:$owner,name:$repo){pullRequest(number:$number){
    mergedAt mergedBy{login}
    reviewThreads(first:100,after:$threads){
      nodes{id isResolved isOutdated path comments(first:100){
        nodes{id body author{login} createdAt}
        pageInfo{hasNextPage endCursor}
      }} pageInfo{hasNextPage endCursor}
    }
    reviewRequests(first:100,after:$requests){
      nodes{requestedReviewer{... on User{login}}}
      pageInfo{hasNextPage endCursor}
    }
  }}
}
"""

_THREAD_COMMENTS_QUERY = """
query($id:ID!,$cursor:String){
  node(id:$id){... on PullRequestReviewThread{
    comments(first:100,after:$cursor){
      nodes{id body author{login} createdAt}
      pageInfo{hasNextPage endCursor}
    }
  }}
}
"""


@dataclass(frozen=True)
class PullRequestSnapshot:
    pr: dict[str, Any]
    checks: tuple[dict[str, Any], ...]
    statuses: tuple[dict[str, Any], ...]
    reviews: tuple[dict[str, Any], ...]
    threads: tuple[dict[str, Any], ...]
    review_requests: tuple[dict[str, Any], ...]
    merged_by: str | None
    merged_at: str | None

    @property
    def head_sha(self) -> str:
        return self.pr["head"]["sha"]

    @property
    def feedback_ids(self) -> tuple[str, ...]:
        return tuple(
            comment["id"]
            for thread in self.threads
            if not thread["isResolved"]
            for comment in thread["comments"]["nodes"]
        )


async def fetch_pr_snapshot(
    gh: GhClient, factory: dict[str, Any], pr_number: int
) -> PullRequestSnapshot:
    root = f"repos/{factory['owner']}/{factory['repo']}"
    pr = await gh.api(f"{root}/pulls/{pr_number}")
    if pr.get("merged"):
        # Merged PRs need attribution, not check/review queries that may disappear.
        checks: list[dict[str, Any]] = []
        statuses: list[dict[str, Any]] = []
        reviews: list[dict[str, Any]] = []
    else:
        checks = []
        page = 1
        while True:
            data = await gh.api(
                f"{root}/commits/{pr['head']['sha']}/check-runs?per_page=100&page={page}"
            )
            checks.extend(data["check_runs"])
            if len(checks) >= data["total_count"]:
                break
            if not data["check_runs"] or page >= 20:
                raise GhError("check pagination incomplete")
            page += 1
        status_pages = await gh.api(
            f"{root}/commits/{pr['head']['sha']}/statuses?per_page=100",
            paginate=True,
        )
        statuses = [item for group in status_pages for item in group]
        review_pages = await gh.api(
            f"{root}/pulls/{pr_number}/reviews?per_page=100", paginate=True
        )
        reviews = [item for group in review_pages for item in group]
    threads: list[dict[str, Any]] = []
    requests: list[dict[str, Any]] = []
    seen_thread_ids: set[str] = set()
    seen_request_keys: set[str] = set()
    thread_cursor = None
    request_cursor = None
    seen_cursors: set[tuple[str | None, str | None]] = set()
    for _ in range(20):
        variables = {
            "owner": factory["owner"],
            "repo": factory["repo"],
            "number": pr_number,
            "threads": thread_cursor,
            "requests": request_cursor,
        }
        response = await gh.api(
            "graphql", method="POST", body={"query": _QUERY, "variables": variables}
        )
        if response.get("errors"):
            raise GhError("GitHub review query failed")
        try:
            info = response["data"]["repository"]["pullRequest"]
            thread_connection = info["reviewThreads"]
            request_connection = info["reviewRequests"]
        except (KeyError, TypeError) as exc:
            raise GhError("GitHub review data is unavailable") from exc
        if info is None:
            raise GhError("GitHub pull request is unavailable")
        for thread in thread_connection["nodes"]:
            if thread["id"] in seen_thread_ids:
                continue
            seen_thread_ids.add(thread["id"])
            comments = thread["comments"]
            comment_cursors: set[str] = set()
            for _ in range(20):
                page_info = comments["pageInfo"]
                if not page_info["hasNextPage"]:
                    break
                cursor = page_info["endCursor"]
                if not cursor or cursor in comment_cursors:
                    raise GhError("review comment pagination incomplete")
                comment_cursors.add(cursor)
                extra = await gh.api(
                    "graphql",
                    method="POST",
                    body={
                        "query": _THREAD_COMMENTS_QUERY,
                        "variables": {"id": thread["id"], "cursor": cursor},
                    },
                )
                if extra.get("errors"):
                    raise GhError("review comment pagination failed")
                try:
                    comments = extra["data"]["node"]["comments"]
                    thread["comments"]["nodes"].extend(comments["nodes"])
                except (KeyError, TypeError) as exc:
                    raise GhError("review comment pagination incomplete") from exc
            else:
                raise GhError("review comment pagination incomplete")
            threads.append(thread)
        for request in request_connection["nodes"]:
            key = str(request)
            if key not in seen_request_keys:
                seen_request_keys.add(key)
                requests.append(request)
        thread_page = thread_connection["pageInfo"]
        request_page = request_connection["pageInfo"]
        if not thread_page["hasNextPage"] and not request_page["hasNextPage"]:
            return PullRequestSnapshot(
                pr,
                tuple(checks),
                tuple(statuses),
                tuple(reviews),
                tuple(threads),
                tuple(requests),
                (info.get("mergedBy") or {}).get("login"),
                info.get("mergedAt"),
            )
        thread_cursor = (
            thread_page["endCursor"] if thread_page["hasNextPage"] else thread_cursor
        )
        request_cursor = (
            request_page["endCursor"] if request_page["hasNextPage"] else request_cursor
        )
        cursor_pair = (thread_cursor, request_cursor)
        if (
            cursor_pair in seen_cursors
            or (thread_page["hasNextPage"] and not thread_cursor)
            or (request_page["hasNextPage"] and not request_cursor)
        ):
            raise GhError("review pagination incomplete")
        seen_cursors.add(cursor_pair)
    raise GhError("review pagination incomplete")

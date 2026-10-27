# PR Review and Merge Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair new PR review feedback and merge only after current-head checks, resolved reviews, and final human approval, while recording manual merges distinctly.

**Architecture:** Keep the standalone extension and its `gh` CLI polling. Add a bounded GitHub PR snapshot adapter; make completion a fail-closed gate; use the host's granted `model_invocation` service capability for background repair runs in fresh Git workspaces. Existing AgentRuns remains the initial interactive development path.

**Tech Stack:** Python 3.12, deerflow-extension-api, gh CLI REST/GraphQL, SQLite, Docker, static ES module UI.

**Spec:** `docs/superpowers/specs/2026-10-16-pr-review-and-merge-gates-design.md`

## Global Constraints

- Keep GitHub credentials and Git operations on Gateway; test commands run only in bounded Docker containers.
- The private acceptance repository has no available GitHub branch-protection/ruleset capability; extension gates must fail closed.
- Poll from Gateway every 180 seconds by default; UI polling is read-only.
- An Agent review is informational and never satisfies final GitHub human approval.
- Never force-push or publish a release.

## Review Focus

- A merged PR whose head moved must finish before stale-head handling: test manual merge after head change.
- A second poll with the same unresolved comment must not rerun repair: test feedback-ID deduplication.
- Missing GraphQL pages or permissions must not become an all-clear: test fail-closed.
- New commits invalidate old human approvals and check evidence: test current-head matching.
- A repair must stop if the PR head or state changes before push: test race handling.

---

### Task 1: GitHub PR evidence adapter

**Files:** `src/deerflow_code_factory/github/gh_cli.py`, new `src/deerflow_code_factory/github/pr_state.py`, `tests/test_pr_state.py`.

**Interfaces:** `GhClient.graphql(query: str, variables: dict | None = None) -> dict`; `PullRequestSnapshot` with merged metadata, head SHA, checks, review requests, latest reviews, review threads, feedback IDs. `fetch_pr_snapshot(gh, factory, pr_number) -> PullRequestSnapshot` paginates every required connection or raises.

- [ ] Write failing tests for merged actor, complete review threads, required checks, stale approval, and paginated/unavailable data.
- [ ] Run focused tests and confirm failures.
- [ ] Implement bounded `gh api graphql` stdin calls plus REST checks/status and snapshot normalization.
- [ ] Run focused tests, Ruff, and commit adapter changes.

### Task 2: Fail-closed completion and manual merge

**Files:** `src/deerflow_code_factory/github/completion.py`, `src/deerflow_code_factory/service.py`, `src/deerflow_code_factory/__init__.py`, `src/deerflow_code_factory/static/index.mjs`, `tests/test_completion.py`, `tests/test_service.py`.

**Interfaces:** `GitHubCompletion.refresh(..., required_checks, approver_logins, prior_merge_attempt) -> dict`; result includes `state`, `reason`, `head_sha`, and merge metadata. PollService records merge intent before invoking the final merge call, and exposes `merged_manual` and `merged_unknown` terminal states.

- [ ] Write failing tests for no approval, unresolved threads, failed/missing checks, stale approval, manual merge, and merge attribution uncertainty.
- [ ] Run focused tests and confirm failures.
- [ ] Implement snapshot-based gate, pre-merge recheck, merge-intent evidence, completion labels, and UI states/reasons.
- [ ] Run focused tests and commit completion changes.

### Task 3: Review repair worker and PR record

**Files:** `src/deerflow_code_factory/workspace.py`, new `src/deerflow_code_factory/review_repair.py`, `src/deerflow_code_factory/service.py`, `src/deerflow_code_factory/supervisor.py`, `src/deerflow_code_factory/github/delivery.py`, `tests/test_review_repair.py`, `tests/test_workspace.py`.

**Interfaces:** `JobWorkspace.prepare_review(owner, repo, branch, head_sha)` and `commit_and_push_review(branch)`; `ReviewRepair.start(job, feedback, model_invoker) -> bool`; worker posts one identified review summary per head and records addressed feedback IDs. `PollService.start(deps)` obtains `deps.model_invoker` for background runs.

- [ ] Write failing tests for one repair per feedback set, Docker/test/review before push, changed PR head stopping push, and successful PR reply.
- [ ] Run focused tests and confirm failures.
- [ ] Implement bounded model calls, fresh checkout, repair loop, independent review, non-force push, and idempotent PR summary/replies.
- [ ] Run focused tests and commit repair changes.

### Task 4: Installation and realistic verification

**Files:** `README.md`, `DESIGN.md`, installed `config.yaml` in isolated DeerFlow checkout, all modified tests.

- [ ] Document operator-only required checks/approver logins and host `model_invocation` role grant; update UI phase copy.
- [ ] Run full Python and Node tests, Ruff check/format, then a real read-only `gh`/GraphQL snapshot against the acceptance repository.
- [ ] Sync and upgrade the standalone extension, restart Gateway/frontend, and confirm health plus page 200.
- [ ] Verify a PR with no human approval remains open, new feedback triggers one repair and PR comment, and an externally merged PR becomes `merged_manual`; record any identity/plan limitation honestly.

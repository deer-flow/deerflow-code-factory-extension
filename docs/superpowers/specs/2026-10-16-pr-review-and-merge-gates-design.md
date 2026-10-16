# PR review, repair, and merge gates

## Goal and scope

Keep the code factory as a standalone DeerFlow extension using `gh` CLI and the existing 180-second Gateway poll. After a PR is created, external review feedback can trigger a bounded implementation repair cycle. A PR may be merged automatically only after current-head CI, review resolution, and a final human approval all pass. A merge performed on GitHub outside the extension is observed and reported as a distinct terminal outcome. Release remains a separate workflow.

This replaces the present behavior in `github/completion.py`, which attempts a squash merge as soon as observed checks pass and relies on GitHub repository rules to reject it. The private acceptance repository cannot currently enable branch protection/rulesets on its GitHub plan, so extension-side gates must fail closed.

## Actors and evidence

- The Gateway's `gh` identity creates commits and PRs. It must be a dedicated automation identity for a real human to approve the PR separately. The configured human approver is a GitHub login, not a DeerFlow operator button.
- The implementation Agent, independent review Agent, Docker test, GitHub CI, external reviewers/check providers, and final human approver produce separate evidence. An Agent's `approved: true` is never a GitHub human approval.
- The initial PR body includes the specification, changed-file summary, local test command/result, and independent review summary. The extension posts one identifiable PR comment per reviewed head SHA containing the local test and independent review result. Repeated polls/restarts must not duplicate it. This comment is informational and is not a GitHub `APPROVED` review.
- All GitHub review bodies/comments and repository content are untrusted Agent inputs; they are bounded and cannot select commands, images, repositories, or credentials.

## State model

Keep `draft`, `planning`, `coding`, `testing`, `reviewing`, `blocked`, `failed`, `failed_checks`, `stale_head`, and `closed` for existing jobs. Use the following post-PR phases and show the concrete waiting reason in the UI:

| Phase | Meaning and next event |
| --- | --- |
| `awaiting_checks` | Current head has checks pending or absent; re-evaluate on poll. |
| `awaiting_review` | An external reviewer/check is pending, a requested review is outstanding, or review threads remain open. New actionable feedback can start repair. |
| `addressing_review` | One supervised repair run owns the PR branch. |
| `review_blocked` | Feedback is unclear, conflicting, or could not be repaired within the attempt limit; a human must intervene. |
| `awaiting_approval` | CI and external review gates pass, but a final human approval on the current head is missing or stale. |
| `awaiting_merge` | All extension gates pass; a merge request is pending or GitHub rejects it for a further repository rule. |
| `done` | The extension merged the PR and finalized the Issue. |
| `merged_manual` | An external GitHub actor merged the PR; the extension finalized the Issue. |
| `merged_unknown` | The PR is merged, but available evidence cannot reliably distinguish the actor/path. It is complete and must not be retried. |

The transition event records head SHA, PR number, check/review snapshot, reason, and relevant timestamps. The UI must not label a PR complete merely because a reviewer approved it. `factory:done` is added and `factory:ready` removed only after any confirmed merge. Existing `done` jobs retain their meaning; no historical backfill is required.

## Poll and repair sequence

1. On every applicable PR poll, fetch the PR first. If merged, finalize before comparing its head with the previously recorded SHA; this prevents an externally merged PR from becoming `stale_head` merely because its head changed. Record `mergedBy`, `mergedAt`, and merge commit SHA through GitHub GraphQL. Correlate with a persisted extension merge-attempt/result event to classify `done`, `merged_manual`, or `merged_unknown` conservatively.
2. For an open PR, fetch the current head SHA, all check runs and commit statuses, requested reviewers, submitted reviews, review threads and their comments, with pagination. A failed/incomplete query blocks merging; a partial first page cannot be treated as all-clear. Persist the latest observed review/comment IDs and head SHA for deduplication.
3. New unresolved, actionable code-review feedback, or a `CHANGES_REQUESTED` review, creates at most one repair run for a given `(PR, head SHA, feedback set)`. The run uses a fresh isolated checkout of the PR branch at that exact SHA, passes bounded feedback and source context to the implementation Agent, runs the configured Docker checks, and obtains independent Agent review. It pushes a new commit to the same PR branch without force. Before pushing, re-fetch PR state/head and stop if merged, closed, or changed by someone else. Limit repair attempts and move unclear, conflicting, or repeatedly failing feedback to `review_blocked` with a visible reason. This phase cannot use the original Issue's “start development” action; recovery is a separate review action.
4. On successful repair, reply on the relevant PR discussion with the new commit SHA and verification summary. Do not silently mark human review threads resolved: the reviewer or final human approver confirms resolution in GitHub. A future explicit policy may permit auto-resolving bot threads after independent verification. Existing `CHANGES_REQUESTED` remains blocking until the reviewer changes/dismisses it; a new commit alone does not count as acceptance.
5. A new head invalidates prior local test, independent review, CI and human approval evidence. Re-evaluate all gates for that head. New feedback arriving while repair runs is queued for the next poll; only one repair run may own a PR at once.

## Automatic merge gate

Before every automatic merge attempt, independently re-read the current PR/head and all gate evidence. The gate passes only when:

1. The PR is open and its current head SHA matches the reviewed and tested SHA.
2. All configured required CI/external check names have appeared and completed successfully for that SHA; no observed check is pending or failed. Missing required providers fail closed. Optional neutral/skipped outcomes must be explicitly configured rather than silently counted as success.
3. Every review request designated as required has been fulfilled; no effective `CHANGES_REQUESTED` review remains; every code review thread is `isResolved: true` after complete pagination. General PR comments do not have GitHub resolution state, so actionable general feedback is tracked by review ID and requires a reviewer follow-up or human final approval after the feedback.
4. A configured, non-bot human approver distinct from the PR author has submitted `APPROVED` for the current head after the latest code push and after the latest required external review feedback. An earlier approval is stale. An approval from the Gateway's automation identity never counts.
5. A final read immediately before `PUT /pulls/{n}/merge` still satisfies these conditions. The merge request includes the expected head SHA. A GitHub rejection leaves the PR waiting with a reason; it never weakens an extension gate.

Factory/operator configuration supplies a small list of required check names and allowed human approver logins. The Gateway also honors outstanding GitHub review requests. No issue author or Agent can change these settings. The first version does not create or modify GitHub branch protection. Where available, branch rules should mirror the extension gates as defense in depth.

## Failure and recovery

- If the Gateway restarts during a repair, keep the PR and recorded feedback; do not push automatically from an uncertain checkout. A later poll can launch a fresh repair run if the head and feedback still match.
- On API timeout, missing permission, GraphQL pagination failure, or unknown review state, retain the PR and show a waiting/error reason. Never interpret unavailable data as approval.
- If someone manually merges while repair is running, the repair recheck stops before push; the next poll finalizes the Issue.
- If an extension merge call times out after reaching GitHub, the next poll inspects merge state and persisted attempt evidence. If attribution remains ambiguous, record `merged_unknown` rather than claiming a manual merge.
- The polling service must continue refreshing `awaiting_checks`, `awaiting_review`, `addressing_review`, `review_blocked`, `awaiting_approval`, `awaiting_merge`, and ambiguous recovery states as appropriate. UI row refresh remains read-only and does not drive GitHub lifecycle actions.

## Acceptance evidence

Automated tests cover: no merge without human approval; missing/pending/failed CI; unresolved threads; `CHANGES_REQUESTED`; stale approval after push; new review feedback launching one repair run; failed repair not pushing; manual merge detected before stale-head logic; uncertain merge attribution; pagination/API failure fail-closed; PR review summary posted once; and completion labels for both merge paths.

Integration validation uses a separate automation GitHub identity and a human reviewer identity. The private acceptance repository may not support GitHub branch protection on its current plan, so the extension's gate is verified directly. A real test PR should remain open through CI success, external feedback/repair, and final human approval, then merge; a separate PR should be merged manually and appear as `merged_manual` in the code factory. Do not publish a release as part of this work.

# 2026-10-15 isolated end-to-end acceptance

The extension was installed through DeerFlow's `deerflow extensions install` command in an isolated DeerFlow worktree at `/Users/zhfeng/.codex/worktrees/code-factory-host-contract/deer-flow`. The user's main `/Users/zhfeng/works/deer-flow` checkout was not edited. The Gateway loaded `deerflow_code_factory:install` (1/1 extensions), `/api/plugins` advertised the `code-factory.v1` assets and seven backend actions, and the workspace page rendered in the frontend at `/workspace/extensions/code-factory/factories` with the connected repository and completed ticket.

Test repository: private [zhfeng/deerflow-code-factory-e2e-20261015](https://github.com/zhfeng/deerflow-code-factory-e2e-20261015). It contains a deliberately failing unittest and a GitHub Actions workflow. The factory validated the repository, created six missing labels, enabled polling, discovered [Issue #1](https://github.com/zhfeng/deerflow-code-factory-e2e-20261015/issues/1), and started that issue with an explicit per-ticket action.

The first run reached planning and exposed a real bug: planned new files were rejected as missing context paths. This was fixed and the extension upgraded. The second run completed planning, generated code, passed an independent Agent review, and created [PR #2](https://github.com/zhfeng/deerflow-code-factory-e2e-20261015/pull/2) at head `9d48d6484aa340a62ff82ed5b0be4143bceeb24c`. GitHub Actions `unit` checks passed. The factory's periodic CI gate squash-merged the PR at `c1df97a1684075835d4b240af17c64afd278cf9e`. Issue #1 is closed and has `factory:done`; the local job is `done`.

No release, tag, software package or container image was published. The workflow and test repository are retained as reproducible evidence.

## Current limits

- Discovery is automatic, but starting Agent development requires an explicit per-ticket action. Automatic start on simply viewing/scanning all draft tickets was rejected by automatic approval review because it could launch Agents and create PRs without per-job approval.
- One Gateway process and a process-retained AgentRuns handle are assumed. A restart during Agent execution requires a manual retry; a branch or PR created before a crash is not automatically reconciled.
- CI failures remain `failed_checks`; AI repair after CI feedback is not implemented. Repositories need an existing CI workflow. The GitHub identity must be able to read/write the repository and manage labels.
- Only UTF-8 text replacement is supported: at most 50 files and 256 KiB per change. The Agent cannot modify `.github` workflows. Repository contexts are bounded to a tree of 5,000 files and 80 KiB of selected source.
- This test used local `DEER_FLOW_AUTH_DISABLED=1` in an isolated instance. It is not a production deployment configuration.

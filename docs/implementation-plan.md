# DeerFlow Code Factory MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone DeerFlow extension that polls GitHub Issues and automatically carries one requirement through design, code, independent review, tests, PR, and merge, without publishing a version.

**Architecture:** A packaged full-stack extension owns one durable factory/job store, a narrow RequirementSource interface, a GitHub adapter, and a supervised phase runner. It calls DeerFlow AgentRuns for full Agent stages and relies on the host sandbox/checkpoints; GitHub writes remain in the trusted adapter. A small host API addition is permitted only if Task 1 proves the public API cannot export a fixed workspace snapshot.

**Tech Stack:** Python 3.12+, deerflow-extension-api 0.2.x, FastAPI/SQLAlchemy or SQLite for the MVP store, GitHub REST API, packaged BrowserAssets UI, pytest.

**Spec:** [spec.md](spec.md)

## Global Constraints

- Scope is one Gateway instance, one GitHub App, one factory per repository; Jira is deferred but RequirementSource stays provider-neutral.
- Poll every 3 minutes by default with jitter; no webhook in MVP.
- Issue completion means merged and accepted; no GitHub Release, version, or container publishing.
- No GitHub credentials in Agent prompts or sandboxes. Never bypass branch protection.
- Every review/test result is bound to the head SHA; three automatic repair rounds maximum.
- Preserve all current uncommitted changes in the deer-flow host checkout.

## Review Focus

- A repo issue list includes PRs: test that PR-shaped entries never create jobs.
- A page fails after earlier pages succeed: test that the cursor stays at the last complete scan.
- A bot comment updates an Issue: test that it does not restart an Agent or answer its own question.
- The head SHA changes after a passing review: test that review and test gates become invalid.
- CI passes but required human review is absent: test that the job remains awaiting_merge.

---

### Task 1: Prove the host integration path

**Files:**
- Create: `docs/host-capability-probe.md`
- Create: `tests/test_host_contract.py`
- Modify only if proven necessary: `/Users/zhfeng/works/deer-flow/backend/packages/extension-api/deerflow_extension_api/` and matching Gateway adapter/tests

**Interfaces:**
- Consumes: `AgentRuns.create_thread/start/get/wait/get_state/cancel`, plugin action context, host artifact/working-directory facilities.
- Produces: documented `WorkspaceSnapshot` acquisition path yielding a fixed file tree and content hash for one user/thread/run.

- [ ] **Step 1: Write failing contract tests** for authenticated AgentRuns availability, a completed run's workspace snapshot, and denial across user/thread boundaries.
- [ ] **Step 2: Run the focused tests** with `cd /Users/zhfeng/works/deer-flow/backend && uv run --locked pytest tests/test_extension_agent_runs.py -q`; record exactly which public capability is missing.
- [ ] **Step 3: Use an existing public host path if sufficient**; otherwise add one generic, read-only `WorkspaceSnapshotReader` to extension-api and Gateway, scoped to the authenticated user/thread and limited in size. Do not add code-factory names to the host contract.
- [ ] **Step 4: Re-run focused host tests** and document the result, API version requirement, size limits, and multi-process limitation.
- [ ] **Step 5: Commit only the reviewed host change** if one was needed; otherwise commit the probe document in this project.

### Task 2: Package, store, and minimal UI

**Files:**
- Create: `pyproject.toml`, `src/deerflow_code_factory/__init__.py`, `src/deerflow_code_factory/store.py`, `src/deerflow_code_factory/models.py`
- Create: `src/deerflow_code_factory/ui_manifest.json`, `src/deerflow_code_factory/static/index.mjs`, `tests/test_store.py`, `tests/test_plugin.py`

**Interfaces:**
- Produces: `install(registry, config)`; `FactoryStore.create_factory(...)`, `create_or_get_job(repository_id, issue_id)`, `transition(job_id, expected_version, phase, evidence)`.

- [ ] **Step 1: Write failing tests** for one factory per repository, unique issue mapping, compare-and-swap transition, and plugin registration against a host test double.
- [ ] **Step 2: Run `uv run pytest tests/test_store.py tests/test_plugin.py -q`** and confirm the expected missing interfaces.
- [ ] **Step 3: Implement the minimal package and SQLite-backed store** with schema versioning and immutable stage events; register BrowserAssets and backend actions for list/create/get/enable/disable/check-now.
- [ ] **Step 4: Add a basic page** with factory list, create form, validation result, latest scan, and job list; no general dashboard framework.
- [ ] **Step 5: Re-run tests and commit** the independently usable extension shell.

### Task 3: GitHub factory setup and validation

**Files:**
- Create: `src/deerflow_code_factory/github/client.py`, `src/deerflow_code_factory/github/setup.py`, `tests/test_github_setup.py`
- Modify: `src/deerflow_code_factory/static/index.mjs`

**Interfaces:**
- Produces: `validate_factory(repo_id) -> ValidationReport`; `ensure_labels(repo_id) -> LabelReport`; `create_or_bind_repository(input) -> Factory`.

- [ ] **Step 1: Write failing tests** for new/existing repo modes, pre-existing labels preserved, missing labels created once, denied permissions, absent default branch, and incompatible branch rules.
- [ ] **Step 2: Run `uv run pytest tests/test_github_setup.py -q`** and confirm failures.
- [ ] **Step 3: Implement GitHub App authenticated REST calls** with allowlisted owner, short-lived installation tokens, minimal permission checks, and user-visible validation reasons.
- [ ] **Step 4: Complete the create/bind/labels/validate UI**; require explicit confirmation of repo creation and label mutations; enable only after validation passes.
- [ ] **Step 5: Re-run tests and commit.**

### Task 4: Narrow ticket adapter and reliable poller

**Files:**
- Create: `src/deerflow_code_factory/requirements.py`, `src/deerflow_code_factory/github/issues.py`, `src/deerflow_code_factory/poller.py`
- Create: `tests/test_requirements.py`, `tests/test_poller.py`

**Interfaces:**
- Produces: `RequirementSource` protocol with `list_candidates`, `fetch`, `list_new_replies`, `post_progress`, `set_phase`; `Poller.scan_factory(factory_id)`.

- [ ] **Step 1: Write failing tests** for filtered issue discovery, PR exclusion, pagination, overlap and dedup, comments, bot-loop avoidance, rate-limit backoff, and cursor preservation after partial failure.
- [ ] **Step 2: Run `uv run pytest tests/test_requirements.py tests/test_poller.py -q`** and confirm failures.
- [ ] **Step 3: Implement GitHubIssueSource and one process-local poll loop** using durable scan cursors; separately recheck tracked issues and blocked-job replies.
- [ ] **Step 4: Add check-now and latest-scan reporting** to UI and test them.
- [ ] **Step 5: Re-run tests and commit.**

### Task 5: Agent stages and readiness gate

**Files:**
- Create: `src/deerflow_code_factory/stages.py`, `src/deerflow_code_factory/readiness.py`, `src/deerflow_code_factory/prompts.py`
- Create: `tests/test_readiness.py`, `tests/test_stages.py`

**Interfaces:**
- Produces: `StageRunner.run(job_id, agent_runs)`; structured `Specification`, `DesignReview`, `ReadinessReport` tied to issue revision and base SHA.

- [ ] **Step 1: Write failing tests** for label admission versus coding readiness, missing acceptance criteria, key ambiguity causing blocked/question, authorized reply resuming, and revised issue invalidating a frozen spec.
- [ ] **Step 2: Run `uv run pytest tests/test_readiness.py tests/test_stages.py -q`** and confirm failures.
- [ ] **Step 3: Implement specification and design stages** using full AgentRuns through an authenticated action, structured output validation, and a service-retained handle during the process lifetime.
- [ ] **Step 4: Implement coding stage** on `code-factory/issue-<number>`, pinning spec version and base SHA; stop on cancellation or Issue revision change.
- [ ] **Step 5: Re-run tests and commit.**

### Task 6: Independent review, deterministic tests, PR, and completion

**Files:**
- Create: `src/deerflow_code_factory/review.py`, `src/deerflow_code_factory/verification.py`, `src/deerflow_code_factory/github/pull_requests.py`
- Create: `tests/test_review.py`, `tests/test_verification.py`, `tests/test_pull_requests.py`

**Interfaces:**
- Produces: `ReviewResult(head_sha, findings)`, `VerificationResult(head_sha, checks)`, `complete_if_merged(job_id)`.

- [ ] **Step 1: Write failing tests** for reviewer isolation, blocker repair, max three repair rounds, SHA invalidation, failing commands, missing required CI, required human approval, and no release side effects.
- [ ] **Step 2: Run focused tests** and confirm failures.
- [ ] **Step 3: Implement independent reviewer Agent and sandbox command runner** using only repository-approved check commands; capture real exit codes and logs.
- [ ] **Step 4: Implement create/update PR, status/ruleset reads, optional auto-merge when policy permits, and completion after confirmed merge SHA.**
- [ ] **Step 5: Re-run focused tests and commit.**

### Task 7: End-to-end acceptance and operator guide

**Files:**
- Create: `tests/test_factory_flow.py`, `docs/operations.md`
- Modify: `README.md`

**Interfaces:** Uses all prior tasks; produces one installable MVP with a reproducible test-repository walkthrough.

- [ ] **Step 1: Write failing end-to-end tests** for clear Issue through merged PR and ambiguous Issue through question/reply/resume.
- [ ] **Step 2: Run the end-to-end tests**, then fix integration gaps without adding generic infrastructure.
- [ ] **Step 3: Exercise one real test repository** with an explicit sandbox and GitHub App installation; record Issue, PR, CI and merged SHA in the acceptance note. Do not run this against a production repository.
- [ ] **Step 4: Document install, config, poll behavior, recovery limits, permissions and disabled release scope** in README/operations.
- [ ] **Step 5: Run `uv run pytest -q` and `uv run ruff check .`; commit only after both pass.**

## Implementation boundary

Tasks 1–4 make setup and Issue intake observable; Task 5 runs design and coding; Task 6 closes the development loop; Task 7 proves the entire workflow. If Task 1 shows that authenticated workspace snapshots or long-lived run control require more than a narrow host API, stop and revise the spec before implementing a private-host workaround.

# Isolated workspace implementation plan

## Files and boundaries

- `workspace.py`: validated per-job checkout, safe file application, diff, commit and push. GitHub credentials remain in the Gateway process.
- `checks.py`: configured Docker image and test command, no-network bounded execution, captured exit status and logs.
- `supervisor.py`: stages run against the checkout, checks and independent review gate PR creation. Existing explicit start remains.
- `stages.py`: coding and review prompts receive checkout context and actual diff/check evidence.
- `github/delivery.py`: create PR for an already pushed branch; keep existing Git Data path for old tests until migrated.
- `__init__.py` and `README.md`: parse operator-only workspace settings and document deployment.

## Tasks

1. Write failing tests for checkout identity/branch safety, path application, Docker command arguments and failed-check stop. Implement bounded workspace and checker modules. Run focused tests.
2. Write failing supervisor tests for clone → code → test → review → commit/push/PR, plus test failure and review repair. Replace direct Git Data delivery for newly started jobs. Run focused tests.
3. Add operator config for workspace root, image and test command. Document limits and recovery. Run full pytest, Ruff, and static checks.
4. Install into isolated DeerFlow instance. Use a fresh test Issue in private acceptance repo to verify local test evidence before PR and the GitHub CI/merge path. Record result; keep release out of scope.

## Safety invariants

- No Issue or Agent text enters shell commands. All process calls use argv and bounded timeouts.
- Workspaces live under the operator configured root and are unique per job. No force push or overwrite of existing branch.
- Docker has no network, credentials, or privileged access. Failed or missing checks block PR creation.
- The base SHA and Issue revision are rechecked before push. Existing PRs keep their current tracking path.

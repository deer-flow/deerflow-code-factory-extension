# Implementation progress

Plan: [implementation-plan.md](implementation-plan.md)

- Completed: extension management page, owner-scoped plugin actions, existing-repository validation, explicit missing-label creation, enable/disable, manual scan, job list, and a single-process periodic poll service. GitHub calls use authenticated `gh` CLI without shell interpolation. Explicit job start now runs specification, implementation, independent review, Git Data API branch/commit/PR creation, and head-bound CI/merge polling. The earlier HTTP adapters remain unused.
- Verified: focused pytest suite, Ruff check, JavaScript syntax check, and offline wheel build. The wheel contains the browser manifest, module, and stylesheet.
- Probe finding: current public extension API lacks a principal-bound workspace/output archive reader; see [host-capability-probe.md](host-capability-probe.md).
- Next: validate installation and page inside a running DeerFlow host, exercise an isolated real GitHub test repository, then harden recovery and CI-failure repair. GitHub App authentication and fully automatic draft-job dispatch are deferred per user direction and approval constraints. Agent output is transferred as bounded structured JSON in the Agent's final reply, avoiding a host API addition for the MVP.

No live GitHub repository was mutated. Publishing remains outside the MVP.

"""DeerFlow code factory extension."""

from pathlib import Path
from typing import Any

from deerflow_extension_api import extension
from deerflow_extension_api.plugins import (
    BackendAction,
    BrowserAssets,
    PluginContribution,
)

from .github.gh_cli import GhClient, GhIssueSource, GhRepositorySetup
from .poller import Poller
from .service import PollService
from .store import FactoryStore
from .supervisor import JobSupervisor


@extension(api="0.2.5", name="code-factory")
def install(registry: Any, config: dict[str, Any]) -> None:
    path = config.get("storage_path")
    enabled = config.get("enabled", False)
    operators = config.get("operator_user_ids")
    if (
        not isinstance(path, str)
        or not Path(path).is_absolute()
        or type(enabled) is not bool
        or not isinstance(operators, list)
        or not operators
        or not all(isinstance(value, str) and value for value in operators)
    ):
        raise ValueError(
            "configure absolute storage_path, boolean enabled and operator_user_ids"
        )
    store = FactoryStore(path)
    setup = GhRepositorySetup(GhClient())
    poller = Poller(store, GhIssueSource(GhClient()))
    supervisor = JobSupervisor(store)
    allowed = set(operators)

    def owner(context: Any) -> str:
        user_id = context.principal.user_id
        if user_id not in allowed:
            raise PermissionError("code factory operator access required")
        return user_id

    async def validate_repository(
        payload: dict[str, Any], context: Any
    ) -> dict[str, Any]:
        owner(context)
        if set(payload) != {"owner", "repo"}:
            raise ValueError("invalid repository fields")
        report = await setup.validate(payload["owner"], payload["repo"])
        return {
            "repository_id": report.repository_id,
            "owner": report.owner,
            "repo": report.repo,
            "ready": report.ready,
            "problems": list(report.problems),
            "missing_labels": list(report.missing_labels),
        }

    async def create_factory(payload: dict[str, Any], context: Any) -> dict[str, Any]:
        user_id = owner(context)
        if (
            set(payload) != {"owner", "repo", "create_labels"}
            or type(payload["create_labels"]) is not bool
        ):
            raise ValueError("invalid factory fields")
        report = await setup.validate(payload["owner"], payload["repo"])
        if not report.ready:
            raise ValueError(
                f"repository validation failed: {', '.join(report.problems)}"
            )
        if report.missing_labels:
            if not payload["create_labels"]:
                raise ValueError("missing factory labels; confirm label creation")
            await setup.ensure_labels(report.owner, report.repo, report)
        return store.create_factory(
            owner_user_id=user_id,
            repository_id=report.repository_id,
            owner=report.owner,
            repo=report.repo,
        )

    async def list_factories(
        payload: dict[str, Any], context: Any
    ) -> list[dict[str, Any]]:
        user_id = owner(context)
        if payload:
            raise ValueError("list_factories takes no fields")
        return store.list_factories(user_id)

    async def set_factory_enabled(
        payload: dict[str, Any], context: Any
    ) -> dict[str, Any]:
        user_id = owner(context)
        if (
            set(payload) != {"factory_id", "enabled"}
            or type(payload["enabled"]) is not bool
        ):
            raise ValueError("invalid factory state fields")
        factory = store.get_factory(payload["factory_id"], owner_user_id=user_id)
        if factory is None:
            raise KeyError(payload["factory_id"])
        if payload["enabled"]:
            report = await setup.validate(factory["owner"], factory["repo"])
            if (
                not report.ready
                or report.missing_labels
                or report.repository_id != factory["repository_id"]
            ):
                raise ValueError(
                    "repository validation failed; check labels and identity"
                )
        return store.set_factory_enabled(
            payload["factory_id"], owner_user_id=user_id, enabled=payload["enabled"]
        )

    async def scan_factory(payload: dict[str, Any], context: Any) -> dict[str, int]:
        user_id = owner(context)
        if set(payload) != {"factory_id"}:
            raise ValueError("invalid scan fields")
        factory = store.get_factory(payload["factory_id"], owner_user_id=user_id)
        if factory is None:
            raise KeyError(payload["factory_id"])
        if not factory["enabled"]:
            raise ValueError("factory is disabled")
        return {"created": await poller.scan_factory(factory["id"])}

    async def list_jobs(payload: dict[str, Any], context: Any) -> list[dict[str, Any]]:
        user_id = owner(context)
        if set(payload) != {"factory_id"}:
            raise ValueError("invalid job list fields")
        factory = store.get_factory(payload["factory_id"], owner_user_id=user_id)
        if factory is None:
            raise KeyError(payload["factory_id"])
        jobs = []
        for job in store.list_jobs(factory["id"]):
            events = store.list_events(job["id"])
            delivery = next(
                (
                    event["evidence"]
                    for event in reversed(events)
                    if "pr_url" in event["evidence"]
                ),
                {},
            )
            latest = events[-1]["evidence"] if events else {}
            jobs.append(
                {
                    **job,
                    "issue_url": f"https://github.com/{factory['owner']}/{factory['repo']}/issues/{job['issue_number']}",
                    "pr_url": delivery.get("pr_url"),
                    "detail": latest.get("reason") or latest.get("question"),
                }
            )
        return jobs

    async def start_job(payload: dict[str, Any], context: Any) -> dict[str, bool]:
        user_id = owner(context)
        if set(payload) != {"job_id"}:
            raise ValueError("invalid job start fields")
        job = store.get_job(payload["job_id"], owner_user_id=user_id)
        if job is None:
            raise KeyError(payload["job_id"])
        return {"started": supervisor.start(job["id"], context.agent_runs)}

    accepted = registry.plugin(
        PluginContribution(
            namespace="code-factory",
            title="代码工厂 / Code factory",
            description="GitHub Issue-driven requirement development.",
            enabled=enabled,
            frontend=BrowserAssets("code-factory.v1", Path(__file__).parent),
            backend=(
                BackendAction("validate_repository", validate_repository),
                BackendAction("create_factory", create_factory),
                BackendAction("list_factories", list_factories),
                BackendAction("set_factory_enabled", set_factory_enabled),
                BackendAction("scan_factory", scan_factory),
                BackendAction("list_jobs", list_jobs),
                BackendAction("start_job", start_job),
            ),
        )
    )
    if accepted is not True:
        raise RuntimeError("code factory requires full-stack plugin support")
    if enabled:
        registry.service(
            PollService(
                store,
                poller,
                config.get("poll_interval_seconds", 180),
                supervisor=supervisor,
            )
        )
